"""
Azure Disk Manager — find unattached managed disks.

Detects managed disks with disk_state == 'Unattached' (not attached to any VM).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from finops_ai.core.base_manager import (
    BaseResourceManager,
    CloudProvider,
    DeleteResult,
    OrphanedResource,
    ResourceStatus,
    ScanResult,
)
from finops_ai.utils.cost_calculator import CostCalculator

logger = logging.getLogger("finops-ai.azure.disk")

# Map Azure SKU names to our tier names
_SKU_TO_TIER = {
    "Standard_LRS": "standard_hdd",
    "StandardSSD_LRS": "standard_ssd",
    "Premium_LRS": "premium_ssd",
    "UltraSSD_LRS": "ultra",
    "StandardSSD_ZRS": "standard_ssd",
    "Premium_ZRS": "premium_ssd",
}


class AzureDiskManager(BaseResourceManager):
    """Finds unattached Azure managed disks that are costing money without use."""

    def __init__(self, credential: Any, subscription_id: Optional[str] = None) -> None:
        try:
            from azure.mgmt.compute import ComputeManagementClient
            from azure.mgmt.resource import SubscriptionClient
        except ImportError:
            raise ImportError("Azure SDK not installed. Install with: pip install finops-ai[azure]")

        self.credential = credential
        self.specific_subscription_id = subscription_id
        self._subscription_client = SubscriptionClient(credential)
        self._compute_clients: Dict[str, Any] = {}

    @property
    def provider(self) -> CloudProvider:
        return CloudProvider.AZURE

    @property
    def resource_type(self) -> str:
        return "disk"

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

    def scan(self) -> ScanResult:
        """Scan for unattached managed disks."""
        resources: List[OrphanedResource] = []
        errors: List[str] = []

        for sub in self._get_subscriptions():
            sub_id, sub_name = sub["id"], sub["name"]
            logger.info(f"Scanning disks in {sub_name} ({sub_id})")

            try:
                compute_client = self._get_compute_client(sub_id)
                disks = list(compute_client.disks.list())

                for disk in disks:
                    # Check if disk is unattached
                    is_unattached = (
                        getattr(disk, "disk_state", None) == "Unattached"
                        or getattr(disk, "managed_by", None) is None
                    )

                    if is_unattached and getattr(disk, "disk_state", "") == "Unattached":
                        size_gb = getattr(disk, "disk_size_gb", 0) or 0
                        sku_name = getattr(disk.sku, "name", "Standard_LRS") if disk.sku else "Standard_LRS"
                        tier = _SKU_TO_TIER.get(sku_name, "standard_hdd")
                        cost = CostCalculator.azure_disk(size_gb, tier)

                        created_time = ""
                        age_days = 0
                        if hasattr(disk, "time_created") and disk.time_created:
                            created_time = disk.time_created.strftime("%Y-%m-%d %H:%M:%S UTC")
                            from datetime import datetime, timezone
                            age_days = (datetime.now(timezone.utc) - disk.time_created).days

                        tags = dict(disk.tags) if getattr(disk, "tags", None) else {}

                        resource = OrphanedResource(
                            provider=CloudProvider.AZURE,
                            resource_type="disk",
                            resource_id=disk.id,
                            name=disk.name,
                            region=getattr(disk, "location", "unknown"),
                            subscription_or_account=sub_id,
                            subscription_name=sub_name,
                            resource_group=disk.id.split("/")[4],
                            status=ResourceStatus.UNATTACHED,
                            size_gb=size_gb,
                            estimated_monthly_cost=cost,
                            age_days=age_days,
                            created_time=created_time,
                            tags=tags,
                            metadata={"sku": sku_name, "tier": tier},
                        )
                        resources.append(resource)

            except Exception as e:
                error_msg = f"Error scanning disks in {sub_id}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        logger.info(f"Found {len(resources)} unattached disks")
        return self.get_scan_result(resources, errors)

    def delete(self, resource_id: str, dry_run: bool = True) -> DeleteResult:
        """Delete an unattached disk."""
        parts = resource_id.split("/")
        if len(parts) < 9:
            return DeleteResult(resource_id=resource_id, resource_name="unknown",
                                success=False, dry_run=dry_run, error_message="Invalid ID")

        sub_id, rg, disk_name = parts[2], parts[4], parts[8]

        if dry_run:
            logger.info(f"DRY RUN: Would delete disk {disk_name}")
            return DeleteResult(resource_id=resource_id, resource_name=disk_name,
                                success=True, dry_run=True)

        try:
            client = self._get_compute_client(sub_id)
            op = client.disks.begin_delete(rg, disk_name)
            op.wait()
            logger.info(f"Deleted disk {disk_name}")
            return DeleteResult(resource_id=resource_id, resource_name=disk_name,
                                success=True, dry_run=False)
        except Exception as e:
            return DeleteResult(resource_id=resource_id, resource_name=disk_name,
                                success=False, dry_run=False, error_message=str(e))

    def estimate_cost(self, resource: OrphanedResource) -> float:
        tier = resource.metadata.get("tier", "standard_hdd")
        return CostCalculator.azure_disk(resource.size_gb, tier)
