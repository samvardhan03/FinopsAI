"""
AWS RDS Manager — find unused RDS snapshots.
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

logger = logging.getLogger("finops-ai.aws.rds")


class AWSRDSManager(BaseResourceManager):
    """Finds unused RDS snapshots (manual snapshots whose DB no longer exists)."""

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
        return "rds"

    def _get_account_id(self) -> str:
        if not self._account_id:
            sts = self.session.client("sts")
            self._account_id = sts.get_caller_identity()["Account"]
        return self._account_id

    def scan(self) -> ScanResult:
        """Scan for orphaned RDS snapshots."""
        resources: List[OrphanedResource] = []
        errors: List[str] = []
        account_id = self._get_account_id()

        for region in self.regions:
            logger.info(f"Scanning RDS snapshots in {region}")
            try:
                rds = self.session.client("rds", region_name=region)

                # Get existing DB instances
                dbs = rds.describe_db_instances()
                existing_dbs = {db["DBInstanceIdentifier"] for db in dbs.get("DBInstances", [])}

                # Get manual snapshots
                snapshots = rds.describe_db_snapshots(SnapshotType="manual")
                for snap in snapshots.get("DBSnapshots", []):
                    db_id = snap.get("DBInstanceIdentifier", "")

                    if db_id and db_id not in existing_dbs:
                        snap_id = snap["DBSnapshotIdentifier"]
                        snap_arn = snap.get("DBSnapshotArn", "")
                        size = snap.get("AllocatedStorage", 0)
                        cost = round(size * 0.095, 2)  # RDS snapshot ~$0.095/GB/month

                        create_time = snap.get("SnapshotCreateTime")
                        age_days = 0
                        created_str = ""
                        if create_time:
                            if create_time.tzinfo is None:
                                create_time = create_time.replace(tzinfo=timezone.utc)
                            age_days = (datetime.now(timezone.utc) - create_time).days
                            created_str = create_time.strftime("%Y-%m-%d %H:%M:%S UTC")

                        resources.append(OrphanedResource(
                            provider=CloudProvider.AWS,
                            resource_type="rds_snapshot",
                            resource_id=snap_arn or f"arn:aws:rds:{region}:{account_id}:snapshot:{snap_id}",
                            name=snap_id,
                            region=region,
                            subscription_or_account=account_id,
                            subscription_name=f"AWS Account {account_id}",
                            status=ResourceStatus.ORPHANED,
                            size_gb=size,
                            estimated_monthly_cost=cost,
                            age_days=age_days,
                            created_time=created_str,
                            source_resource_id=db_id,
                            metadata={
                                "engine": snap.get("Engine", ""),
                                "engine_version": snap.get("EngineVersion", ""),
                                "db_identifier": db_id,
                            },
                        ))

            except Exception as e:
                error_msg = f"Error scanning RDS in {region}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        logger.info(f"Found {len(resources)} orphaned RDS snapshots")
        return self.get_scan_result(resources, errors)

    def delete(self, resource_id: str, dry_run: bool = True) -> DeleteResult:
        resource_name = resource_id.split(":")[-1]

        if dry_run:
            logger.info(f"DRY RUN: Would delete RDS snapshot {resource_name}")
            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=True, dry_run=True)

        try:
            parts = resource_id.split(":")
            region = parts[3] if len(parts) > 3 else "us-east-1"
            rds = self.session.client("rds", region_name=region)
            rds.delete_db_snapshot(DBSnapshotIdentifier=resource_name)
            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=True, dry_run=False)
        except Exception as e:
            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=False, dry_run=False, error_message=str(e))

    def estimate_cost(self, resource: OrphanedResource) -> float:
        return round(resource.size_gb * 0.095, 2)
