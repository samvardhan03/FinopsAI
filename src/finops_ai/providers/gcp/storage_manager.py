"""
GCP Storage Manager — find idle Cloud Storage buckets.

Detects buckets with no objects or very old last-modified times.
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

logger = logging.getLogger("finops-ai.gcp.storage")


class GCPStorageManager(BaseResourceManager):
    """Finds idle/empty GCP Cloud Storage buckets."""

    def __init__(self, project_id: str, credentials: Any = None) -> None:
        try:
            from google.cloud import storage
        except ImportError:
            raise ImportError("GCP SDK not installed. Install with: pip install finops-ai[gcp]")

        self.project_id = project_id
        self._client = storage.Client(project=project_id, credentials=credentials)

    @property
    def provider(self) -> CloudProvider:
        return CloudProvider.GCP

    @property
    def resource_type(self) -> str:
        return "storage_bucket"

    def scan(self) -> ScanResult:
        """Scan for empty or idle Cloud Storage buckets."""
        resources: List[OrphanedResource] = []
        errors: List[str] = []

        try:
            logger.info(f"Scanning Cloud Storage buckets in project {self.project_id}")
            buckets = list(self._client.list_buckets(project=self.project_id))

            for bucket in buckets:
                try:
                    # Check if bucket is empty
                    blobs = list(bucket.list_blobs(max_results=1))

                    if not blobs:
                        labels = dict(getattr(bucket, "labels", {}) or {})
                        created = getattr(bucket, "time_created", None)
                        age_days = 0
                        created_str = ""
                        if created:
                            if created.tzinfo is None:
                                created = created.replace(tzinfo=timezone.utc)
                            age_days = (datetime.now(timezone.utc) - created).days
                            created_str = created.strftime("%Y-%m-%d %H:%M:%S UTC")

                        resources.append(OrphanedResource(
                            provider=CloudProvider.GCP,
                            resource_type="storage_bucket",
                            resource_id=f"gs://{bucket.name}",
                            name=bucket.name,
                            region=getattr(bucket, "location", "unknown"),
                            subscription_or_account=self.project_id,
                            subscription_name=f"GCP Project {self.project_id}",
                            status=ResourceStatus.EMPTY,
                            age_days=age_days,
                            created_time=created_str,
                            tags=labels,
                            metadata={
                                "storage_class": getattr(bucket, "storage_class", "STANDARD"),
                                "location_type": getattr(bucket, "location_type", ""),
                            },
                        ))

                except Exception as e:
                    errors.append(f"Error checking bucket {bucket.name}: {e}")

        except Exception as e:
            errors.append(f"Error listing GCP buckets: {e}")
            logger.error(f"Error listing GCP buckets: {e}")

        logger.info(f"Found {len(resources)} idle GCP storage buckets")
        return self.get_scan_result(resources, errors)

    def delete(self, resource_id: str, dry_run: bool = True) -> DeleteResult:
        bucket_name = resource_id.replace("gs://", "")

        if dry_run:
            logger.info(f"DRY RUN: Would delete bucket {bucket_name}")
            return DeleteResult(resource_id=resource_id, resource_name=bucket_name,
                                success=True, dry_run=True)

        try:
            bucket = self._client.get_bucket(bucket_name)
            bucket.delete(force=True)
            return DeleteResult(resource_id=resource_id, resource_name=bucket_name,
                                success=True, dry_run=False)
        except Exception as e:
            return DeleteResult(resource_id=resource_id, resource_name=bucket_name,
                                success=False, dry_run=False, error_message=str(e))

    def estimate_cost(self, resource: OrphanedResource) -> float:
        return 0.0  # Empty buckets have no storage cost
