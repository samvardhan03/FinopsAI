"""
Azure App Service Manager — find unused App Service Plans.

Detects App Service Plans with no web apps deployed to them.
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

logger = logging.getLogger("finops-ai.azure.appservice")


class AzureAppServiceManager(BaseResourceManager):
    """Finds unused Azure App Service Plans (no apps assigned)."""

    def __init__(self, credential: Any, subscription_id: Optional[str] = None) -> None:
        try:
            from azure.mgmt.web import WebSiteManagementClient
            from azure.mgmt.resource import SubscriptionClient
        except ImportError:
            raise ImportError("Azure SDK not installed. Install with: pip install finops-ai[azure]")

        self.credential = credential
        self.specific_subscription_id = subscription_id
        self._subscription_client = SubscriptionClient(credential)
        self._web_clients: Dict[str, Any] = {}

    @property
    def provider(self) -> CloudProvider:
        return CloudProvider.AZURE

    @property
    def resource_type(self) -> str:
        return "app_service_plan"

    def _get_web_client(self, subscription_id: str) -> Any:
        if subscription_id not in self._web_clients:
            from azure.mgmt.web import WebSiteManagementClient
            self._web_clients[subscription_id] = WebSiteManagementClient(
                self.credential, subscription_id
            )
        return self._web_clients[subscription_id]

    def _get_subscriptions(self) -> List[Dict[str, str]]:
        if self.specific_subscription_id:
            sub = self._subscription_client.subscriptions.get(self.specific_subscription_id)
            return [{"id": sub.subscription_id, "name": sub.display_name}]
        subs = list(self._subscription_client.subscriptions.list())
        return [{"id": s.subscription_id, "name": s.display_name} for s in subs]

    def scan(self) -> ScanResult:
        """Scan for unused App Service Plans."""
        resources: List[OrphanedResource] = []
        errors: List[str] = []

        for sub in self._get_subscriptions():
            sub_id, sub_name = sub["id"], sub["name"]
            logger.info(f"Scanning App Service Plans in {sub_name}")

            try:
                web_client = self._get_web_client(sub_id)
                plans = list(web_client.app_service_plans.list())

                for plan in plans:
                    # Check number of apps
                    num_sites = getattr(plan, "number_of_sites", 0) or 0

                    if num_sites == 0:
                        # Free/Shared tiers have no cost
                        sku = getattr(plan, "sku", None)
                        sku_tier = getattr(sku, "tier", "Free") if sku else "Free"
                        sku_name = getattr(sku, "name", "F1") if sku else "F1"

                        if sku_tier.lower() in ("free", "shared"):
                            continue  # Skip free plans

                        # Rough cost estimation by SKU
                        cost_map = {
                            "B1": 13.14, "B2": 26.28, "B3": 52.56,
                            "S1": 73.00, "S2": 146.00, "S3": 292.00,
                            "P1v2": 73.00, "P2v2": 146.00, "P3v2": 292.00,
                            "P1v3": 95.63, "P2v3": 191.25, "P3v3": 382.50,
                        }
                        estimated_cost = cost_map.get(sku_name, 50.0)

                        rg = plan.id.split("/")[4]
                        tags = dict(plan.tags) if getattr(plan, "tags", None) else {}

                        resources.append(OrphanedResource(
                            provider=CloudProvider.AZURE,
                            resource_type="app_service_plan",
                            resource_id=plan.id,
                            name=plan.name,
                            region=getattr(plan, "location", "unknown"),
                            subscription_or_account=sub_id,
                            subscription_name=sub_name,
                            resource_group=rg,
                            status=ResourceStatus.EMPTY,
                            estimated_monthly_cost=estimated_cost,
                            tags=tags,
                            metadata={
                                "sku_name": sku_name,
                                "sku_tier": sku_tier,
                                "number_of_sites": num_sites,
                            },
                        ))

            except Exception as e:
                error_msg = f"Error scanning App Service Plans in {sub_id}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        logger.info(f"Found {len(resources)} unused App Service Plans")
        return self.get_scan_result(resources, errors)

    def delete(self, resource_id: str, dry_run: bool = True) -> DeleteResult:
        """Delete an App Service Plan."""
        parts = resource_id.split("/")
        if len(parts) < 9:
            return DeleteResult(resource_id=resource_id, resource_name="unknown",
                                success=False, dry_run=dry_run, error_message="Invalid ID")

        sub_id, rg, plan_name = parts[2], parts[4], parts[8]

        if dry_run:
            logger.info(f"DRY RUN: Would delete App Service Plan {plan_name}")
            return DeleteResult(resource_id=resource_id, resource_name=plan_name,
                                success=True, dry_run=True)

        try:
            client = self._get_web_client(sub_id)
            client.app_service_plans.delete(rg, plan_name)
            return DeleteResult(resource_id=resource_id, resource_name=plan_name,
                                success=True, dry_run=False)
        except Exception as e:
            return DeleteResult(resource_id=resource_id, resource_name=plan_name,
                                success=False, dry_run=False, error_message=str(e))

    def estimate_cost(self, resource: OrphanedResource) -> float:
        return resource.estimated_monthly_cost
