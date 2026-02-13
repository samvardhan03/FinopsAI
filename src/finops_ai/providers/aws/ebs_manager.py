"""
AWS EBS Manager — find unattached volumes and orphaned snapshots.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
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

logger = logging.getLogger("finops-ai.aws.ebs")


class AWSEBSManager(BaseResourceManager):
    """Finds unattached EBS volumes and orphaned EBS snapshots."""

    def __init__(self, session: Any, regions: Optional[List[str]] = None) -> None:
        try:
            import boto3
        except ImportError:
            raise ImportError("AWS SDK not installed. Install with: pip install finops-ai[aws]")

        self.session = session
        self.regions = regions or ["us-east-1"]
        self._account_id: Optional[str] = None

    @property
    def provider(self) -> CloudProvider:
        return CloudProvider.AWS

    @property
    def resource_type(self) -> str:
        return "ebs"

    def _get_account_id(self) -> str:
        if not self._account_id:
            sts = self.session.client("sts")
            self._account_id = sts.get_caller_identity()["Account"]
        return self._account_id

    def scan(self) -> ScanResult:
        """Scan for unattached EBS volumes and orphaned snapshots."""
        resources: List[OrphanedResource] = []
        errors: List[str] = []
        account_id = self._get_account_id()

        for region in self.regions:
            logger.info(f"Scanning EBS in {region}")
            try:
                ec2 = self.session.client("ec2", region_name=region)

                # ── Unattached Volumes ─────────────────────────────────
                volumes = ec2.describe_volumes(
                    Filters=[{"Name": "status", "Values": ["available"]}]
                )
                for vol in volumes.get("Volumes", []):
                    vol_id = vol["VolumeId"]
                    size = vol.get("Size", 0)
                    vol_type = vol.get("VolumeType", "gp3")
                    cost = CostCalculator.aws_ebs_volume(size, vol_type)

                    create_time = vol.get("CreateTime")
                    age_days = 0
                    created_str = ""
                    if create_time:
                        if create_time.tzinfo is None:
                            create_time = create_time.replace(tzinfo=timezone.utc)
                        age_days = (datetime.now(timezone.utc) - create_time).days
                        created_str = create_time.strftime("%Y-%m-%d %H:%M:%S UTC")

                    tags = {t["Key"]: t["Value"] for t in vol.get("Tags", [])}
                    name = tags.get("Name", vol_id)

                    resources.append(OrphanedResource(
                        provider=CloudProvider.AWS,
                        resource_type="ebs_volume",
                        resource_id=f"arn:aws:ec2:{region}:{account_id}:volume/{vol_id}",
                        name=name,
                        region=region,
                        subscription_or_account=account_id,
                        subscription_name=f"AWS Account {account_id}",
                        status=ResourceStatus.UNATTACHED,
                        size_gb=size,
                        estimated_monthly_cost=cost,
                        age_days=age_days,
                        created_time=created_str,
                        tags=tags,
                        metadata={"volume_type": vol_type, "volume_id": vol_id},
                    ))

                # ── Orphaned Snapshots ─────────────────────────────────
                snapshots = ec2.describe_snapshots(OwnerIds=["self"])
                # Build set of existing volumes
                all_vols = ec2.describe_volumes()
                existing_vol_ids = {v["VolumeId"] for v in all_vols.get("Volumes", [])}

                for snap in snapshots.get("Snapshots", []):
                    source_vol = snap.get("VolumeId", "")
                    if source_vol and source_vol not in existing_vol_ids:
                        snap_id = snap["SnapshotId"]
                        size = snap.get("VolumeSize", 0)
                        cost = CostCalculator.aws_snapshot(size)

                        start_time = snap.get("StartTime")
                        age_days = 0
                        created_str = ""
                        if start_time:
                            if start_time.tzinfo is None:
                                start_time = start_time.replace(tzinfo=timezone.utc)
                            age_days = (datetime.now(timezone.utc) - start_time).days
                            created_str = start_time.strftime("%Y-%m-%d %H:%M:%S UTC")

                        tags = {t["Key"]: t["Value"] for t in snap.get("Tags", [])}
                        name = tags.get("Name", snap_id)

                        resources.append(OrphanedResource(
                            provider=CloudProvider.AWS,
                            resource_type="ebs_snapshot",
                            resource_id=f"arn:aws:ec2:{region}:{account_id}:snapshot/{snap_id}",
                            name=name,
                            region=region,
                            subscription_or_account=account_id,
                            subscription_name=f"AWS Account {account_id}",
                            status=ResourceStatus.ORPHANED,
                            size_gb=size,
                            estimated_monthly_cost=cost,
                            age_days=age_days,
                            created_time=created_str,
                            tags=tags,
                            source_resource_id=source_vol,
                            metadata={"snapshot_id": snap_id},
                        ))

            except Exception as e:
                error_msg = f"Error scanning EBS in {region}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        logger.info(f"Found {len(resources)} EBS resources to review")
        return self.get_scan_result(resources, errors)

    def delete(self, resource_id: str, dry_run: bool = True) -> DeleteResult:
        resource_name = resource_id.split("/")[-1]

        if dry_run:
            logger.info(f"DRY RUN: Would delete {resource_id}")
            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=True, dry_run=True)

        try:
            parts = resource_id.split(":")
            region = parts[3] if len(parts) > 3 else "us-east-1"
            ec2 = self.session.client("ec2", region_name=region)

            if "volume/" in resource_id:
                ec2.delete_volume(VolumeId=resource_name)
            elif "snapshot/" in resource_id:
                ec2.delete_snapshot(SnapshotId=resource_name)

            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=True, dry_run=False)
        except Exception as e:
            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=False, dry_run=False, error_message=str(e))

    def estimate_cost(self, resource: OrphanedResource) -> float:
        if resource.resource_type == "ebs_volume":
            vol_type = resource.metadata.get("volume_type", "gp3")
            return CostCalculator.aws_ebs_volume(resource.size_gb, vol_type)
        return CostCalculator.aws_snapshot(resource.size_gb)
