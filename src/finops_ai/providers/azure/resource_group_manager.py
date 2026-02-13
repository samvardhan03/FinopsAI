"""
Azure Resource Group Manager — find empty/orphaned resource groups.

Detects resource groups with zero resources inside them.
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

logger = logging.getLogger("finops-ai.azure.rg")


class AzureResourceGroupManager(BaseResourceManager):
    """Finds empty Azure resource groups (containing zero resources)."""

    def __init__(self, credential: Any, subscription_id: Optional[str] = None) -> None:
        try:
            from azure.mgmt.resource import ResourceManagementClient, SubscriptionClient
        except ImportError:
            raise ImportError("Azure SDK not installed. Install with: pip install finops-ai[azure]")

        self.credential = credential
        self.specific_subscription_id = subscription_id
        self._subscription_client = SubscriptionClient(credential)
        self._resource_clients: Dict[str, Any] = {}

    @property
    def provider(self) -> CloudProvider:
        return CloudProvider.AZURE

    @property
    def resource_type(self) -> str:
        return "resource_group"

    def _get_resource_client(self, subscription_id: str) -> Any:
        if subscription_id not in self._resource_clients:
            from azure.mgmt.resource import ResourceManagementClient
            self._resource_clients[subscription_id] = ResourceManagementClient(
                self.credential, subscription_id
            )
        return self._resource_clients[subscription_id]

    def _get_subscriptions(self) -> List[Dict[str, str]]:
        if self.specific_subscription_id:
            sub = self._subscription_client.subscriptions.get(self.specific_subscription_id)
            return [{"id": sub.subscription_id, "name": sub.display_name}]
        subs = list(self._subscription_client.subscriptions.list())
        return [{"id": s.subscription_id, "name": s.display_name} for s in subs]

    def scan(self) -> ScanResult:
        """Scan for empty resource groups."""
        resources: List[OrphanedResource] = []
        errors: List[str] = []

        for sub in self._get_subscriptions():
            sub_id, sub_name = sub["id"], sub["name"]
            logger.info(f"Scanning resource groups in {sub_name}")

            try:
                client = self._get_resource_client(sub_id)
                rgs = list(client.resource_groups.list())

                for rg in rgs:
                    # Count resources in this RG
                    try:
                        resource_list = list(
                            client.resources.list_by_resource_group(rg.name, top=1)
                        )
                        if len(resource_list) == 0:
                            tags = dict(rg.tags) if getattr(rg, "tags", None) else {}
                            resources.append(OrphanedResource(
                                provider=CloudProvider.AZURE,
                                resource_type="resource_group",
                                resource_id=rg.id,
                                name=rg.name,
                                region=getattr(rg, "location", "unknown"),
                                subscription_or_account=sub_id,
                                subscription_name=sub_name,
                                resource_group=rg.name,
                                status=ResourceStatus.EMPTY,
                                estimated_monthly_cost=0.0,
                                tags=tags,
                            ))
                    except Exception as e:
                        logger.warning(f"Error checking resources in RG {rg.name}: {e}")

            except Exception as e:
                error_msg = f"Error scanning resource groups in {sub_id}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        logger.info(f"Found {len(resources)} empty resource groups")
        return self.get_scan_result(resources, errors)

    def delete(self, resource_id: str, dry_run: bool = True) -> DeleteResult:
        """Delete an empty resource group."""
        parts = resource_id.split("/")
        if len(parts) < 5:
            return DeleteResult(resource_id=resource_id, resource_name="unknown",
                                success=False, dry_run=dry_run, error_message="Invalid ID")

        sub_id = parts[2]
        rg_name = parts[4]

        if dry_run:
            logger.info(f"DRY RUN: Would delete resource group {rg_name}")
            return DeleteResult(resource_id=resource_id, resource_name=rg_name,
                                success=True, dry_run=True)

        try:
            client = self._get_resource_client(sub_id)
            op = client.resource_groups.begin_delete(rg_name)
            op.wait()
            return DeleteResult(resource_id=resource_id, resource_name=rg_name,
                                success=True, dry_run=False)
        except Exception as e:
            return DeleteResult(resource_id=resource_id, resource_name=rg_name,
                                success=False, dry_run=False, error_message=str(e))

    def estimate_cost(self, resource: OrphanedResource) -> float:
        return 0.0  # Resource groups themselves are free
