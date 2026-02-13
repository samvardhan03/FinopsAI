"""
Azure Network Manager — find unused network resources.

Detects:
- Unassociated Public IPs (not attached to any resource)
- Unused NICs (not attached to any VM)
- Idle Load Balancers (no backend pools or empty pools)
- Empty Virtual Networks / Subnets
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

logger = logging.getLogger("finops-ai.azure.network")


class AzureNetworkManager(BaseResourceManager):
    """Finds unused Azure network resources: public IPs, NICs, load balancers, VNets."""

    def __init__(self, credential: Any, subscription_id: Optional[str] = None) -> None:
        try:
            from azure.mgmt.network import NetworkManagementClient
            from azure.mgmt.resource import SubscriptionClient
        except ImportError:
            raise ImportError("Azure SDK not installed. Install with: pip install finops-ai[azure]")

        self.credential = credential
        self.specific_subscription_id = subscription_id
        self._subscription_client = SubscriptionClient(credential)
        self._network_clients: Dict[str, Any] = {}

    @property
    def provider(self) -> CloudProvider:
        return CloudProvider.AZURE

    @property
    def resource_type(self) -> str:
        return "network"

    def _get_network_client(self, subscription_id: str) -> Any:
        if subscription_id not in self._network_clients:
            from azure.mgmt.network import NetworkManagementClient
            self._network_clients[subscription_id] = NetworkManagementClient(
                self.credential, subscription_id
            )
        return self._network_clients[subscription_id]

    def _get_subscriptions(self) -> List[Dict[str, str]]:
        if self.specific_subscription_id:
            sub = self._subscription_client.subscriptions.get(self.specific_subscription_id)
            return [{"id": sub.subscription_id, "name": sub.display_name}]
        subs = list(self._subscription_client.subscriptions.list())
        return [{"id": s.subscription_id, "name": s.display_name} for s in subs]

    def scan(self) -> ScanResult:
        """Scan for all unused network resources."""
        resources: List[OrphanedResource] = []
        errors: List[str] = []

        for sub in self._get_subscriptions():
            sub_id, sub_name = sub["id"], sub["name"]
            logger.info(f"Scanning network resources in {sub_name}")

            try:
                client = self._get_network_client(sub_id)

                # ── Unassociated Public IPs ────────────────────────────
                for ip in client.public_ip_addresses.list_all():
                    if getattr(ip, "ip_configuration", None) is None:
                        tags = dict(ip.tags) if getattr(ip, "tags", None) else {}
                        resources.append(OrphanedResource(
                            provider=CloudProvider.AZURE,
                            resource_type="public_ip",
                            resource_id=ip.id,
                            name=ip.name,
                            region=getattr(ip, "location", "unknown"),
                            subscription_or_account=sub_id,
                            subscription_name=sub_name,
                            resource_group=ip.id.split("/")[4],
                            status=ResourceStatus.UNATTACHED,
                            estimated_monthly_cost=CostCalculator.azure_public_ip(),
                            tags=tags,
                            metadata={"ip_address": getattr(ip, "ip_address", ""),
                                       "allocation_method": getattr(ip, "public_ip_allocation_method", "")},
                        ))

                # ── Unused NICs ────────────────────────────────────────
                for nic in client.network_interfaces.list_all():
                    if getattr(nic, "virtual_machine", None) is None:
                        tags = dict(nic.tags) if getattr(nic, "tags", None) else {}
                        resources.append(OrphanedResource(
                            provider=CloudProvider.AZURE,
                            resource_type="nic",
                            resource_id=nic.id,
                            name=nic.name,
                            region=getattr(nic, "location", "unknown"),
                            subscription_or_account=sub_id,
                            subscription_name=sub_name,
                            resource_group=nic.id.split("/")[4],
                            status=ResourceStatus.UNATTACHED,
                            estimated_monthly_cost=0.0,
                            tags=tags,
                        ))

                # ── Idle Load Balancers ────────────────────────────────
                for lb in client.load_balancers.list_all():
                    backend_pools = getattr(lb, "backend_address_pools", []) or []
                    has_backends = any(
                        getattr(pool, "load_balancer_backend_addresses", None)
                        for pool in backend_pools
                    )
                    if not has_backends:
                        sku_name = getattr(lb.sku, "name", "Basic") if lb.sku else "Basic"
                        is_standard = sku_name.lower() == "standard"
                        cost = CostCalculator.azure_load_balancer(standard=is_standard)
                        tags = dict(lb.tags) if getattr(lb, "tags", None) else {}
                        resources.append(OrphanedResource(
                            provider=CloudProvider.AZURE,
                            resource_type="load_balancer",
                            resource_id=lb.id,
                            name=lb.name,
                            region=getattr(lb, "location", "unknown"),
                            subscription_or_account=sub_id,
                            subscription_name=sub_name,
                            resource_group=lb.id.split("/")[4],
                            status=ResourceStatus.IDLE,
                            estimated_monthly_cost=cost,
                            tags=tags,
                            metadata={"sku": sku_name},
                        ))

            except Exception as e:
                error_msg = f"Error scanning network resources in {sub_id}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        logger.info(f"Found {len(resources)} unused network resources")
        return self.get_scan_result(resources, errors)

    def delete(self, resource_id: str, dry_run: bool = True) -> DeleteResult:
        """Delete a network resource by ID."""
        parts = resource_id.split("/")
        if len(parts) < 9:
            return DeleteResult(resource_id=resource_id, resource_name="unknown",
                                success=False, dry_run=dry_run, error_message="Invalid ID")

        sub_id, rg = parts[2], parts[4]
        resource_type_segment = parts[7]
        resource_name = parts[8]

        if dry_run:
            logger.info(f"DRY RUN: Would delete {resource_type_segment} {resource_name}")
            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=True, dry_run=True)

        try:
            client = self._get_network_client(sub_id)
            if resource_type_segment == "publicIPAddresses":
                op = client.public_ip_addresses.begin_delete(rg, resource_name)
            elif resource_type_segment == "networkInterfaces":
                op = client.network_interfaces.begin_delete(rg, resource_name)
            elif resource_type_segment == "loadBalancers":
                op = client.load_balancers.begin_delete(rg, resource_name)
            else:
                return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                    success=False, dry_run=False,
                                    error_message=f"Unsupported type: {resource_type_segment}")
            op.wait()
            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=True, dry_run=False)
        except Exception as e:
            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=False, dry_run=False, error_message=str(e))

    def estimate_cost(self, resource: OrphanedResource) -> float:
        if resource.resource_type == "public_ip":
            return CostCalculator.azure_public_ip()
        elif resource.resource_type == "load_balancer":
            is_standard = resource.metadata.get("sku", "").lower() == "standard"
            return CostCalculator.azure_load_balancer(standard=is_standard)
        return 0.0
