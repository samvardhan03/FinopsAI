"""
GCP Network Manager — find unused static IPs and idle forwarding rules.
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

logger = logging.getLogger("finops-ai.gcp.network")


class GCPNetworkManager(BaseResourceManager):
    """Finds unused GCP network resources: static IPs, idle forwarding rules."""

    def __init__(self, project_id: str, credentials: Any = None, regions: Optional[List[str]] = None) -> None:
        try:
            from google.cloud import compute_v1
        except ImportError:
            raise ImportError("GCP SDK not installed. Install with: pip install finops-ai[gcp]")

        self.project_id = project_id
        self.credentials = credentials
        self.regions = regions or []
        self._addresses_client = compute_v1.AddressesClient(credentials=credentials)
        self._global_addresses_client = compute_v1.GlobalAddressesClient(credentials=credentials)
        self._regions_client = compute_v1.RegionsClient(credentials=credentials)

    @property
    def provider(self) -> CloudProvider:
        return CloudProvider.GCP

    @property
    def resource_type(self) -> str:
        return "network"

    def _get_regions(self) -> List[str]:
        if self.regions:
            return self.regions
        regions = self._regions_client.list(project=self.project_id)
        return [r.name for r in regions]

    def scan(self) -> ScanResult:
        """Scan for unused static IPs."""
        resources: List[OrphanedResource] = []
        errors: List[str] = []

        # ── Regional static IPs ───────────────────────────────────────
        try:
            for region in self._get_regions():
                try:
                    addresses = self._addresses_client.list(project=self.project_id, region=region)
                    for addr in addresses:
                        status = getattr(addr, "status", "")
                        if status == "RESERVED":  # Not IN_USE
                            labels = dict(getattr(addr, "labels", {}) or {})
                            resources.append(OrphanedResource(
                                provider=CloudProvider.GCP,
                                resource_type="static_ip",
                                resource_id=f"projects/{self.project_id}/regions/{region}/addresses/{addr.name}",
                                name=addr.name,
                                region=region,
                                subscription_or_account=self.project_id,
                                subscription_name=f"GCP Project {self.project_id}",
                                status=ResourceStatus.UNATTACHED,
                                estimated_monthly_cost=CostCalculator.gcp_static_ip(),
                                tags=labels,
                                metadata={"address": getattr(addr, "address", "")},
                            ))
                except Exception as e:
                    errors.append(f"Error scanning IPs in {region}: {e}")

        except Exception as e:
            errors.append(f"Error listing GCP regions: {e}")

        # ── Global static IPs ─────────────────────────────────────────
        try:
            global_addrs = self._global_addresses_client.list(project=self.project_id)
            for addr in global_addrs:
                status = getattr(addr, "status", "")
                if status == "RESERVED":
                    labels = dict(getattr(addr, "labels", {}) or {})
                    resources.append(OrphanedResource(
                        provider=CloudProvider.GCP,
                        resource_type="static_ip",
                        resource_id=f"projects/{self.project_id}/global/addresses/{addr.name}",
                        name=addr.name,
                        region="global",
                        subscription_or_account=self.project_id,
                        subscription_name=f"GCP Project {self.project_id}",
                        status=ResourceStatus.UNATTACHED,
                        estimated_monthly_cost=CostCalculator.gcp_static_ip(),
                        tags=labels,
                        metadata={"address": getattr(addr, "address", "")},
                    ))
        except Exception as e:
            errors.append(f"Error scanning global IPs: {e}")

        logger.info(f"Found {len(resources)} unused GCP network resources")
        return self.get_scan_result(resources, errors)

    def delete(self, resource_id: str, dry_run: bool = True) -> DeleteResult:
        resource_name = resource_id.split("/")[-1]

        if dry_run:
            logger.info(f"DRY RUN: Would delete {resource_id}")
            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=True, dry_run=True)

        try:
            if "/global/" in resource_id:
                op = self._global_addresses_client.delete(project=self.project_id, address=resource_name)
            else:
                region = resource_id.split("/regions/")[1].split("/")[0]
                op = self._addresses_client.delete(project=self.project_id, region=region, address=resource_name)

            op.result()
            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=True, dry_run=False)
        except Exception as e:
            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=False, dry_run=False, error_message=str(e))

    def estimate_cost(self, resource: OrphanedResource) -> float:
        return CostCalculator.gcp_static_ip()
