"""
GCP Compute Manager — find orphaned disks, snapshots, and stopped VMs.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from finops_ai.core.base_manager import (
    BaseResourceManager,
    CloudProvider,
    DeleteResult,
    OrphanedResource,
    ResourceStatus,
    ScanResult,
)
from finops_ai.utils.cost_calculator import CostCalculator

logger = logging.getLogger("finops-ai.gcp.compute")


class GCPComputeManager(BaseResourceManager):
    """Finds orphaned disks, snapshots, and stopped VMs in Google Cloud."""

    def __init__(self, project_id: str, credentials: Any = None, zones: Optional[List[str]] = None) -> None:
        try:
            from google.cloud import compute_v1
        except ImportError:
            raise ImportError("GCP SDK not installed. Install with: pip install finops-ai[gcp]")

        self.project_id = project_id
        self.credentials = credentials
        self.zones = zones or []
        self._disks_client = compute_v1.DisksClient(credentials=credentials)
        self._snapshots_client = compute_v1.SnapshotsClient(credentials=credentials)
        self._instances_client = compute_v1.InstancesClient(credentials=credentials)
        self._zones_client = compute_v1.ZonesClient(credentials=credentials)

    @property
    def provider(self) -> CloudProvider:
        return CloudProvider.GCP

    @property
    def resource_type(self) -> str:
        return "compute"

    def _get_zones(self) -> List[str]:
        if self.zones:
            return self.zones
        zones = self._zones_client.list(project=self.project_id)
        return [z.name for z in zones]

    def scan(self) -> ScanResult:
        """Scan for orphaned compute resources."""
        resources: List[OrphanedResource] = []
        errors: List[str] = []

        # ── Orphaned Snapshots ─────────────────────────────────────────
        try:
            logger.info(f"Scanning snapshots in project {self.project_id}")
            snapshots = self._snapshots_client.list(project=self.project_id)

            for snap in snapshots:
                source_disk = getattr(snap, "source_disk", "")
                # Check if source disk still exists
                if source_disk:
                    try:
                        # Parse source disk path to verify existence
                        parts = source_disk.split("/")
                        zone = parts[-3] if len(parts) > 3 else ""
                        disk_name = parts[-1] if parts else ""
                        self._disks_client.get(project=self.project_id, zone=zone, disk=disk_name)
                    except Exception:
                        # Source disk doesn't exist — snapshot is orphaned
                        size_gb = int(getattr(snap, "disk_size_gb", 0) or 0)
                        cost = CostCalculator.gcp_snapshot(size_gb)

                        labels = dict(getattr(snap, "labels", {}) or {})
                        resources.append(OrphanedResource(
                            provider=CloudProvider.GCP,
                            resource_type="snapshot",
                            resource_id=f"projects/{self.project_id}/global/snapshots/{snap.name}",
                            name=snap.name,
                            region="global",
                            subscription_or_account=self.project_id,
                            subscription_name=f"GCP Project {self.project_id}",
                            status=ResourceStatus.ORPHANED,
                            size_gb=size_gb,
                            estimated_monthly_cost=cost,
                            tags=labels,
                            source_resource_id=source_disk,
                        ))

        except Exception as e:
            errors.append(f"Error scanning GCP snapshots: {e}")
            logger.error(f"Error scanning GCP snapshots: {e}")

        # ── Unattached Disks ───────────────────────────────────────────
        try:
            logger.info("Scanning for unattached disks")
            for zone in self._get_zones():
                try:
                    disks = self._disks_client.list(project=self.project_id, zone=zone)
                    for disk in disks:
                        users = list(getattr(disk, "users", []) or [])
                        if not users:
                            size_gb = int(getattr(disk, "size_gb", 0) or 0)
                            disk_type = getattr(disk, "type", "pd-standard").split("/")[-1]
                            cost = CostCalculator.gcp_disk(size_gb, disk_type)

                            labels = dict(getattr(disk, "labels", {}) or {})
                            resources.append(OrphanedResource(
                                provider=CloudProvider.GCP,
                                resource_type="disk",
                                resource_id=f"projects/{self.project_id}/zones/{zone}/disks/{disk.name}",
                                name=disk.name,
                                region=zone,
                                subscription_or_account=self.project_id,
                                subscription_name=f"GCP Project {self.project_id}",
                                status=ResourceStatus.UNATTACHED,
                                size_gb=size_gb,
                                estimated_monthly_cost=cost,
                                tags=labels,
                                metadata={"disk_type": disk_type},
                            ))
                except Exception as e:
                    errors.append(f"Error scanning disks in {zone}: {e}")

        except Exception as e:
            errors.append(f"Error scanning GCP disks: {e}")

        # ── Stopped VMs ────────────────────────────────────────────────
        try:
            logger.info("Scanning for stopped VMs")
            for zone in self._get_zones():
                try:
                    instances = self._instances_client.list(project=self.project_id, zone=zone)
                    for vm in instances:
                        status = getattr(vm, "status", "")
                        if status == "TERMINATED":
                            labels = dict(getattr(vm, "labels", {}) or {})
                            resources.append(OrphanedResource(
                                provider=CloudProvider.GCP,
                                resource_type="vm",
                                resource_id=f"projects/{self.project_id}/zones/{zone}/instances/{vm.name}",
                                name=vm.name,
                                region=zone,
                                subscription_or_account=self.project_id,
                                subscription_name=f"GCP Project {self.project_id}",
                                status=ResourceStatus.ZOMBIE,
                                tags=labels,
                                metadata={"machine_type": getattr(vm, "machine_type", "").split("/")[-1]},
                            ))
                except Exception as e:
                    errors.append(f"Error scanning VMs in {zone}: {e}")

        except Exception as e:
            errors.append(f"Error scanning GCP VMs: {e}")

        logger.info(f"Found {len(resources)} GCP compute resources to review")
        return self.get_scan_result(resources, errors)

    def delete(self, resource_id: str, dry_run: bool = True) -> DeleteResult:
        resource_name = resource_id.split("/")[-1]

        if dry_run:
            logger.info(f"DRY RUN: Would delete {resource_id}")
            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=True, dry_run=True)

        try:
            if "/snapshots/" in resource_id:
                op = self._snapshots_client.delete(project=self.project_id, snapshot=resource_name)
            elif "/disks/" in resource_id:
                zone = resource_id.split("/zones/")[1].split("/")[0]
                op = self._disks_client.delete(project=self.project_id, zone=zone, disk=resource_name)
            elif "/instances/" in resource_id:
                zone = resource_id.split("/zones/")[1].split("/")[0]
                op = self._instances_client.delete(project=self.project_id, zone=zone, instance=resource_name)
            else:
                return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                    success=False, dry_run=False, error_message="Unknown resource type")

            op.result()
            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=True, dry_run=False)
        except Exception as e:
            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=False, dry_run=False, error_message=str(e))

    def estimate_cost(self, resource: OrphanedResource) -> float:
        if resource.resource_type == "snapshot":
            return CostCalculator.gcp_snapshot(resource.size_gb)
        elif resource.resource_type == "disk":
            disk_type = resource.metadata.get("disk_type", "pd-standard")
            return CostCalculator.gcp_disk(resource.size_gb, disk_type)
        return 0.0
