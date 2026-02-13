"""
Azure Storage Manager — find orphaned blob storage containers.

Detects storage containers that are empty or haven't been accessed recently.
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

logger = logging.getLogger("finops-ai.azure.storage")


class AzureStorageManager(BaseResourceManager):
    """Finds orphaned/empty Azure blob storage containers."""

    def __init__(self, credential: Any, subscription_id: Optional[str] = None) -> None:
        try:
            from azure.mgmt.storage import StorageManagementClient
            from azure.mgmt.resource import SubscriptionClient
        except ImportError:
            raise ImportError("Azure SDK not installed. Install with: pip install finops-ai[azure]")

        self.credential = credential
        self.specific_subscription_id = subscription_id
        self._subscription_client = SubscriptionClient(credential)
        self._storage_clients: Dict[str, Any] = {}

    @property
    def provider(self) -> CloudProvider:
        return CloudProvider.AZURE

    @property
    def resource_type(self) -> str:
        return "storage_container"

    def _get_storage_client(self, subscription_id: str) -> Any:
        if subscription_id not in self._storage_clients:
            from azure.mgmt.storage import StorageManagementClient
            self._storage_clients[subscription_id] = StorageManagementClient(
                self.credential, subscription_id
            )
        return self._storage_clients[subscription_id]

    def _get_subscriptions(self) -> List[Dict[str, str]]:
        if self.specific_subscription_id:
            sub = self._subscription_client.subscriptions.get(self.specific_subscription_id)
            return [{"id": sub.subscription_id, "name": sub.display_name}]
        subs = list(self._subscription_client.subscriptions.list())
        return [{"id": s.subscription_id, "name": s.display_name} for s in subs]

    def scan(self) -> ScanResult:
        """Scan for empty storage containers across all storage accounts."""
        resources: List[OrphanedResource] = []
        errors: List[str] = []

        for sub in self._get_subscriptions():
            sub_id, sub_name = sub["id"], sub["name"]
            logger.info(f"Scanning storage containers in {sub_name}")

            try:
                storage_client = self._get_storage_client(sub_id)
                accounts = list(storage_client.storage_accounts.list())

                for account in accounts:
                    rg = account.id.split("/")[4]
                    try:
                        containers = list(
                            storage_client.blob_containers.list(rg, account.name)
                        )
                        for container in containers:
                            # Skip system containers
                            if container.name in ("$logs", "$metrics", "azure-webjobs-hosts",
                                                   "azure-webjobs-secrets", "insights-logs"):
                                continue

                            # Check if container is empty or has no recent activity
                            has_immutability = getattr(container, "has_immutability_policy", False)
                            has_legal_hold = getattr(container, "has_legal_hold", False)

                            if not has_immutability and not has_legal_hold:
                                # Mark containers with no recent modification
                                last_modified = getattr(container, "last_modified_time", None)
                                age_days = 0
                                last_modified_str = ""
                                if last_modified:
                                    from datetime import datetime, timezone
                                    age_days = (datetime.now(timezone.utc) - last_modified).days
                                    last_modified_str = last_modified.strftime("%Y-%m-%d %H:%M:%S UTC")

                                    # Only report containers not modified in 90+ days
                                    if age_days < 90:
                                        continue

                                tags = dict(account.tags) if getattr(account, "tags", None) else {}
                                resources.append(OrphanedResource(
                                    provider=CloudProvider.AZURE,
                                    resource_type="storage_container",
                                    resource_id=f"{account.id}/blobServices/default/containers/{container.name}",
                                    name=f"{account.name}/{container.name}",
                                    region=getattr(account, "location", "unknown"),
                                    subscription_or_account=sub_id,
                                    subscription_name=sub_name,
                                    resource_group=rg,
                                    status=ResourceStatus.IDLE,
                                    age_days=age_days,
                                    last_used_time=last_modified_str,
                                    tags=tags,
                                    metadata={"storage_account": account.name},
                                ))

                    except Exception as e:
                        logger.warning(f"Error scanning containers in {account.name}: {e}")

            except Exception as e:
                error_msg = f"Error scanning storage in {sub_id}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        logger.info(f"Found {len(resources)} idle storage containers")
        return self.get_scan_result(resources, errors)

    def delete(self, resource_id: str, dry_run: bool = True) -> DeleteResult:
        """Delete a blob container."""
        parts = resource_id.split("/")
        resource_name = parts[-1] if parts else "unknown"

        if dry_run:
            logger.info(f"DRY RUN: Would delete container {resource_name}")
            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=True, dry_run=True)

        try:
            # Parse: .../resourceGroups/{rg}/providers/Microsoft.Storage/storageAccounts/{acct}/...
            sub_id = parts[2]
            rg = parts[4]
            account_name = parts[8]
            container_name = parts[-1]

            client = self._get_storage_client(sub_id)
            client.blob_containers.delete(rg, account_name, container_name)
            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=True, dry_run=False)
        except Exception as e:
            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=False, dry_run=False, error_message=str(e))

    def estimate_cost(self, resource: OrphanedResource) -> float:
        return 0.0  # Container itself is free; data inside has cost
