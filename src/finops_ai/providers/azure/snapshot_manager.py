"""
Azure Snapshot Manager — find and clean up orphaned managed snapshots.

Migrated from the original TerraSnap-Govern AzureSnapshotManager with:
- Unified OrphanedResource output format
- Cost estimation
- BaseResourceManager contract
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

logger = logging.getLogger("finops-ai.azure.snapshot")


class AzureSnapshotManager(BaseResourceManager):
    """
    Manages Azure managed snapshots — detects orphaned snapshots
    whose source disks no longer exist.

    Migrated from the original TerraSnap-Govern project.
    """

    def __init__(self, credential: Any, subscription_id: Optional[str] = None) -> None:
        """
        Initialize the Azure snapshot manager.

        Args:
            credential: Azure credential object (from AuthManager).
            subscription_id: Specific subscription ID, or None to scan all.
        """
        try:
            from azure.mgmt.compute import ComputeManagementClient
            from azure.mgmt.resource import SubscriptionClient
        except ImportError:
            raise ImportError("Azure SDK not installed. Install with: pip install finops-ai[azure]")

        self.credential = credential
        self.specific_subscription_id = subscription_id
        self._subscription_client = SubscriptionClient(credential)
        self._compute_clients: Dict[str, Any] = {}
        self._disk_cache: Dict[str, bool] = {}

    @property
    def provider(self) -> CloudProvider:
        return CloudProvider.AZURE

    @property
    def resource_type(self) -> str:
        return "snapshot"

    def _get_compute_client(self, subscription_id: str) -> Any:
        """Get or create a ComputeManagementClient for the given subscription."""
        if subscription_id not in self._compute_clients:
            from azure.mgmt.compute import ComputeManagementClient
            self._compute_clients[subscription_id] = ComputeManagementClient(
                self.credential, subscription_id
            )
        return self._compute_clients[subscription_id]

    def _get_subscriptions(self) -> List[Dict[str, str]]:
        """Get list of subscriptions to scan."""
        if self.specific_subscription_id:
            sub = self._subscription_client.subscriptions.get(self.specific_subscription_id)
            return [{"id": sub.subscription_id, "name": sub.display_name}]

        subs = list(self._subscription_client.subscriptions.list())
        return [{"id": s.subscription_id, "name": s.display_name} for s in subs]

    def _disk_exists(self, subscription_id: str, source_resource_id: str) -> bool:
        """Check if a source disk exists (with caching)."""
        cache_key = f"{subscription_id}:{source_resource_id}"
        if cache_key in self._disk_cache:
            return self._disk_cache[cache_key]

        parts = source_resource_id.split("/")
        if len(parts) < 9 or parts[6] != "Microsoft.Compute" or parts[7] != "disks":
            self._disk_cache[cache_key] = False
            return False

        resource_group = parts[4]
        disk_name = parts[8]

        try:
            from azure.core.exceptions import AzureError
            compute_client = self._get_compute_client(subscription_id)
            compute_client.disks.get(resource_group, disk_name)
            self._disk_cache[cache_key] = True
            return True
        except Exception:
            self._disk_cache[cache_key] = False
            return False

    def scan(self) -> ScanResult:
        """Scan all subscriptions for orphaned snapshots."""
        resources: List[OrphanedResource] = []
        errors: List[str] = []
        subscriptions = self._get_subscriptions()

        logger.info(f"Scanning {len(subscriptions)} subscription(s) for orphaned snapshots")

        for sub in subscriptions:
            sub_id = sub["id"]
            sub_name = sub["name"]
            logger.info(f"Scanning subscription: {sub_name} ({sub_id})")

            try:
                compute_client = self._get_compute_client(sub_id)
                snapshots = list(compute_client.snapshots.list())
                logger.info(f"Found {len(snapshots)} snapshots in {sub_name}")

                for snapshot in snapshots:
                    if (
                        hasattr(snapshot, "creation_data")
                        and hasattr(snapshot.creation_data, "source_resource_id")
                        and snapshot.creation_data.source_resource_id
                    ):
                        source_disk_id = snapshot.creation_data.source_resource_id

                        if not self._disk_exists(sub_id, source_disk_id):
                            size_gb = getattr(snapshot, "disk_size_gb", 0) or 0
                            created_time = ""
                            age_days = 0

                            if hasattr(snapshot, "time_created") and snapshot.time_created:
                                created_time = snapshot.time_created.strftime("%Y-%m-%d %H:%M:%S UTC")
                                from datetime import datetime, timezone
                                now = datetime.now(timezone.utc)
                                age_days = (now - snapshot.time_created).days

                            tags = {}
                            if hasattr(snapshot, "tags") and snapshot.tags:
                                tags = dict(snapshot.tags)

                            cost = self.estimate_cost_static(size_gb)

                            resource = OrphanedResource(
                                provider=CloudProvider.AZURE,
                                resource_type="snapshot",
                                resource_id=snapshot.id,
                                name=snapshot.name,
                                region=getattr(snapshot, "location", "unknown"),
                                subscription_or_account=sub_id,
                                subscription_name=sub_name,
                                resource_group=snapshot.id.split("/")[4],
                                status=ResourceStatus.ORPHANED,
                                size_gb=size_gb,
                                estimated_monthly_cost=cost,
                                age_days=age_days,
                                created_time=created_time,
                                tags=tags,
                                source_resource_id=source_disk_id,
                            )
                            resources.append(resource)

            except Exception as e:
                error_msg = f"Error scanning subscription {sub_id}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        logger.info(f"Found {len(resources)} orphaned snapshots across all subscriptions")
        return self.get_scan_result(resources, errors)

    def delete(self, resource_id: str, dry_run: bool = True) -> DeleteResult:
        """Delete a specific snapshot."""
        parts = resource_id.split("/")
        if len(parts) < 9:
            return DeleteResult(
                resource_id=resource_id,
                resource_name="unknown",
                success=False,
                dry_run=dry_run,
                error_message=f"Invalid resource ID format: {resource_id}",
            )

        sub_id = parts[2]
        resource_group = parts[4]
        snapshot_name = parts[8]

        if dry_run:
            logger.info(f"DRY RUN: Would delete snapshot {snapshot_name} in {resource_group}")
            return DeleteResult(
                resource_id=resource_id,
                resource_name=snapshot_name,
                success=True,
                dry_run=True,
            )

        try:
            compute_client = self._get_compute_client(sub_id)
            operation = compute_client.snapshots.begin_delete(resource_group, snapshot_name)
            operation.wait()
            logger.info(f"Deleted snapshot {snapshot_name}")
            return DeleteResult(
                resource_id=resource_id,
                resource_name=snapshot_name,
                success=True,
                dry_run=False,
            )
        except Exception as e:
            logger.error(f"Failed to delete snapshot {snapshot_name}: {e}")
            return DeleteResult(
                resource_id=resource_id,
                resource_name=snapshot_name,
                success=False,
                dry_run=False,
                error_message=str(e),
            )

    def estimate_cost(self, resource: OrphanedResource) -> float:
        """Estimate monthly cost of a snapshot."""
        return CostCalculator.azure_snapshot(resource.size_gb)

    @staticmethod
    def estimate_cost_static(size_gb: float) -> float:
        """Static cost estimation without a resource object."""
        return CostCalculator.azure_snapshot(size_gb)
