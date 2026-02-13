"""
Azure VM Manager — detect zombie VMs (powered off for extended periods).

A "zombie VM" is a VM that has been in a deallocated/stopped state for more than
a configurable threshold (default: 30 days). Even stopped VMs incur disk costs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from finops_ai.core.base_manager import (
    BaseResourceManager,
    CloudProvider,
    DeleteResult,
    OrphanedResource,
    ResourceStatus,
    ScanResult,
)

logger = logging.getLogger("finops-ai.azure.vm")


class AzureVMManager(BaseResourceManager):
    """Detects zombie Azure VMs — deallocated for more than N days."""

    def __init__(
        self,
        credential: Any,
        subscription_id: Optional[str] = None,
        zombie_days: int = 30,
    ) -> None:
        try:
            from azure.mgmt.compute import ComputeManagementClient
            from azure.mgmt.resource import SubscriptionClient
        except ImportError:
            raise ImportError("Azure SDK not installed. Install with: pip install finops-ai[azure]")

        self.credential = credential
        self.specific_subscription_id = subscription_id
        self.zombie_days = zombie_days
        self._subscription_client = SubscriptionClient(credential)
        self._compute_clients: Dict[str, Any] = {}

    @property
    def provider(self) -> CloudProvider:
        return CloudProvider.AZURE

    @property
    def resource_type(self) -> str:
        return "vm"

    def _get_compute_client(self, subscription_id: str) -> Any:
        if subscription_id not in self._compute_clients:
            from azure.mgmt.compute import ComputeManagementClient
            self._compute_clients[subscription_id] = ComputeManagementClient(
                self.credential, subscription_id
            )
        return self._compute_clients[subscription_id]

    def _get_subscriptions(self) -> List[Dict[str, str]]:
        if self.specific_subscription_id:
            sub = self._subscription_client.subscriptions.get(self.specific_subscription_id)
            return [{"id": sub.subscription_id, "name": sub.display_name}]
        subs = list(self._subscription_client.subscriptions.list())
        return [{"id": s.subscription_id, "name": s.display_name} for s in subs]

    def _get_power_state(self, compute_client: Any, rg: str, vm_name: str) -> Optional[str]:
        """Get the power state of a VM."""
        try:
            instance_view = compute_client.virtual_machines.instance_view(rg, vm_name)
            for status in getattr(instance_view, "statuses", []):
                if hasattr(status, "code") and status.code.startswith("PowerState/"):
                    return status.code.split("/")[1]
        except Exception:
            pass
        return None

    def scan(self) -> ScanResult:
        """Scan for zombie VMs (deallocated > zombie_days)."""
        resources: List[OrphanedResource] = []
        errors: List[str] = []

        for sub in self._get_subscriptions():
            sub_id, sub_name = sub["id"], sub["name"]
            logger.info(f"Scanning VMs in {sub_name}")

            try:
                compute_client = self._get_compute_client(sub_id)
                vms = list(compute_client.virtual_machines.list_all())

                for vm in vms:
                    rg = vm.id.split("/")[4]
                    power_state = self._get_power_state(compute_client, rg, vm.name)

                    if power_state in ("deallocated", "stopped"):
                        # Estimate age — use time_created if available
                        age_days = 0
                        created_time = ""
                        if hasattr(vm, "time_created") and vm.time_created:
                            created_time = vm.time_created.strftime("%Y-%m-%d %H:%M:%S UTC")
                            age_days = (datetime.now(timezone.utc) - vm.time_created).days

                        # Only report if stopped longer than threshold
                        if age_days >= self.zombie_days or self.zombie_days == 0:
                            # Estimate disk costs (VMs still pay for OS disk when stopped)
                            os_disk_size = 0
                            if hasattr(vm, "storage_profile") and vm.storage_profile:
                                os_disk = getattr(vm.storage_profile, "os_disk", None)
                                if os_disk:
                                    os_disk_size = getattr(os_disk, "disk_size_gb", 30) or 30

                            # Rough cost: OS disk + data disks
                            estimated_cost = os_disk_size * 0.04  # Assume standard HDD

                            tags = dict(vm.tags) if getattr(vm, "tags", None) else {}
                            vm_size = ""
                            if hasattr(vm, "hardware_profile") and vm.hardware_profile:
                                vm_size = getattr(vm.hardware_profile, "vm_size", "")

                            resources.append(OrphanedResource(
                                provider=CloudProvider.AZURE,
                                resource_type="vm",
                                resource_id=vm.id,
                                name=vm.name,
                                region=getattr(vm, "location", "unknown"),
                                subscription_or_account=sub_id,
                                subscription_name=sub_name,
                                resource_group=rg,
                                status=ResourceStatus.ZOMBIE,
                                size_gb=os_disk_size,
                                estimated_monthly_cost=estimated_cost,
                                age_days=age_days,
                                created_time=created_time,
                                tags=tags,
                                metadata={
                                    "power_state": power_state,
                                    "vm_size": vm_size,
                                    "os_disk_size_gb": os_disk_size,
                                },
                            ))

            except Exception as e:
                error_msg = f"Error scanning VMs in {sub_id}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        logger.info(f"Found {len(resources)} zombie VMs")
        return self.get_scan_result(resources, errors)

    def delete(self, resource_id: str, dry_run: bool = True) -> DeleteResult:
        """Delete (deallocate and remove) a VM."""
        parts = resource_id.split("/")
        if len(parts) < 9:
            return DeleteResult(resource_id=resource_id, resource_name="unknown",
                                success=False, dry_run=dry_run, error_message="Invalid ID")

        sub_id, rg, vm_name = parts[2], parts[4], parts[8]

        if dry_run:
            logger.info(f"DRY RUN: Would delete VM {vm_name}")
            return DeleteResult(resource_id=resource_id, resource_name=vm_name,
                                success=True, dry_run=True)

        try:
            client = self._get_compute_client(sub_id)
            op = client.virtual_machines.begin_delete(rg, vm_name)
            op.wait()
            return DeleteResult(resource_id=resource_id, resource_name=vm_name,
                                success=True, dry_run=False)
        except Exception as e:
            return DeleteResult(resource_id=resource_id, resource_name=vm_name,
                                success=False, dry_run=False, error_message=str(e))

    def estimate_cost(self, resource: OrphanedResource) -> float:
        """Estimate cost — stopped VMs still pay for disks."""
        os_disk_gb = resource.metadata.get("os_disk_size_gb", 30)
        return round(os_disk_gb * 0.04, 2)
