

import argparse
import datetime
import json
import logging
import os
import sys
from typing import Dict, List, Tuple, Optional, Any

from azure.identity import DefaultAzureCredential, ManagedIdentityCredential, ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.resource import ResourceManagementClient, SubscriptionClient
from azure.core.exceptions import AzureError
try:
    from tabulate import tabulate
except ImportError:
    tabulate = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('azure-snapshot-cleanup')


class AzureSnapshotManager:
    """Manages Azure snapshots across subscriptions"""

    def __init__(
        self,
        credential,
        subscription_id: str = None,
        log_level: str = "INFO"
    ):
        """
        Initialize the snapshot manager

        Args:
            credential: Azure credential object
            subscription_id: Specific subscription ID to use (optional)
            log_level: Logging level (default: INFO)
        """
        self.credential = credential
        self.specific_subscription_id = subscription_id
        
        # Set logging level
        logger.setLevel(getattr(logging, log_level))
        
        # Initialize clients
        self.subscription_client = SubscriptionClient(self.credential)
        
        # Store compute clients for each subscription
        self.compute_clients = {}
        self.resource_clients = {}
        
        # Cache for disk lookups
        self.disk_cache = {}
        
        # Results storage
        self.orphaned_snapshots = []

    def get_subscriptions(self) -> List[Dict]:
        """
        Get list of accessible subscriptions
        
        Returns:
            List of subscription dictionaries
        """
        subscriptions = []
        
        if self.specific_subscription_id:
            logger.info(f"Using specific subscription: {self.specific_subscription_id}")
            subscription_detail = self.subscription_client.subscriptions.get(self.specific_subscription_id)
            subscriptions = [{
                'id': subscription_detail.subscription_id,
                'name': subscription_detail.display_name
            }]
        else:
            logger.info("Getting list of accessible subscriptions")
            subscription_list = list(self.subscription_client.subscriptions.list())
            subscriptions = [{'id': sub.subscription_id, 'name': sub.display_name} for sub in subscription_list]
            
        logger.info(f"Found {len(subscriptions)} accessible subscription(s)")
        return subscriptions

    def _get_compute_client(self, subscription_id: str) -> ComputeManagementClient:
        """
        Get or create compute client for subscription
        
        Args:
            subscription_id: Azure subscription ID
            
        Returns:
            ComputeManagementClient for the subscription
        """
        if subscription_id not in self.compute_clients:
            self.compute_clients[subscription_id] = ComputeManagementClient(
                self.credential, subscription_id
            )
        return self.compute_clients[subscription_id]

    def _get_resource_client(self, subscription_id: str) -> ResourceManagementClient:
        """
        Get or create resource client for subscription
        
        Args:
            subscription_id: Azure subscription ID
            
        Returns:
            ResourceManagementClient for the subscription
        """
        if subscription_id not in self.resource_clients:
            self.resource_clients[subscription_id] = ResourceManagementClient(
                self.credential, subscription_id
            )
        return self.resource_clients[subscription_id]

    def disk_exists(self, subscription_id: str, source_resource_id: str) -> bool:
        """
        Check if a disk exists
        
        Args:
            subscription_id: Azure subscription ID
            source_resource_id: Resource ID of the disk
            
        Returns:
            True if disk exists, False otherwise
        """
        # Check cache first
        cache_key = f"{subscription_id}:{source_resource_id}"
        if cache_key in self.disk_cache:
            return self.disk_cache[cache_key]
        
        # Parse the resource ID to extract resource group and disk name
        # Format: /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Compute/disks/{name}
        parts = source_resource_id.split('/')
        
        # Check if this ID format is valid for a disk
        if len(parts) < 9 or parts[6] != 'Microsoft.Compute' or parts[7] != 'disks':
            logger.warning(f"Invalid disk resource ID format: {source_resource_id}")
            self.disk_cache[cache_key] = False
            return False
            
        resource_group = parts[4]
        disk_name = parts[8]
        
        try:
            compute_client = self._get_compute_client(subscription_id)
            compute_client.disks.get(resource_group, disk_name)
            self.disk_cache[cache_key] = True
            return True
        except AzureError:
            self.disk_cache[cache_key] = False
            return False

    def find_orphaned_snapshots(self) -> List[Dict]:
        """
        Find snapshots with detached source disks
        
        Returns:
            List of orphaned snapshot dictionaries
        """
        self.orphaned_snapshots = []
        subscriptions = self.get_subscriptions()
        
        for subscription in subscriptions:
            sub_id = subscription['id']
            logger.info(f"Scanning snapshots in subscription: {subscription['name']} ({sub_id})")
            
            compute_client = self._get_compute_client(sub_id)
            
            # Get all snapshots in the subscription
            try:
                snapshots = list(compute_client.snapshots.list())
                logger.info(f"Found {len(snapshots)} snapshots in subscription")
                
                for snapshot in snapshots:
                    # Check if snapshot has a source disk property
                    if hasattr(snapshot, 'creation_data') and \
                       hasattr(snapshot.creation_data, 'source_resource_id') and \
                       snapshot.creation_data.source_resource_id:
                        
                        source_disk_id = snapshot.creation_data.source_resource_id
                        
                        # Check if source disk exists
                        if not self.disk_exists(sub_id, source_disk_id):
                            # This is an orphaned snapshot
                            size_gb = snapshot.disk_size_gb if hasattr(snapshot, 'disk_size_gb') else 0
                            
                            # Format creation time
                            created_time = "Unknown"
                            if hasattr(snapshot, 'time_created'):
                                created_time = snapshot.time_created.strftime('%Y-%m-%d %H:%M:%S UTC') \
                                    if snapshot.time_created else "Unknown"
                            
                            # Get snapshot tags
                            tags = snapshot.tags if hasattr(snapshot, 'tags') and snapshot.tags else {}
                            
                            orphaned_snapshot = {
                                'subscription_id': sub_id,
                                'subscription_name': subscription['name'],
                                'resource_group': snapshot.id.split('/')[4],
                                'name': snapshot.name,
                                'id': snapshot.id,
                                'source_disk_id': source_disk_id,
                                'size_gb': size_gb,
                                'created_time': created_time,
                                'tags': tags
                            }
                            
                            self.orphaned_snapshots.append(orphaned_snapshot)
                
            except AzureError as e:
                logger.error(f"Error scanning snapshots in subscription {sub_id}: {str(e)}")
                
        logger.info(f"Found {len(self.orphaned_snapshots)} orphaned snapshots across all subscriptions")
        return self.orphaned_snapshots

    def delete_orphaned_snapshots(self, dry_run: bool = True) -> Tuple[int, int]:
        """
        Delete orphaned snapshots
        
        Args:
            dry_run: If True, don't actually delete snapshots
            
        Returns:
            Tuple of (successful_deletions, failed_deletions)
        """
        if not self.orphaned_snapshots:
            logger.info("No orphaned snapshots to delete")
            return (0, 0)
            
        successful = 0
        failed = 0
        
        for snapshot in self.orphaned_snapshots:
            sub_id = snapshot['subscription_id']
            resource_group = snapshot['resource_group']
            snapshot_name = snapshot['name']
            
            try:
                if dry_run:
                    logger.info(f"DRY RUN: Would delete snapshot {snapshot_name} in {resource_group}")
                    successful += 1
                else:
                    logger.info(f"Deleting snapshot {snapshot_name} in {resource_group}")
                    compute_client = self._get_compute_client(sub_id)
                    
                    # Start the deletion operation
                    delete_operation = compute_client.snapshots.begin_delete(
                        resource_group,
                        snapshot_name
                    )
                    
                    # Wait for the operation to complete
                    delete_operation.wait()
                    
                    logger.info(f"Successfully deleted snapshot {snapshot_name}")
                    successful += 1
            except AzureError as e:
                logger.error(f"Failed to delete snapshot {snapshot_name}: {str(e)}")
                failed += 1
                
        return (successful, failed)

    def export_to_json(self, file_path: str) -> None:
        """
        Export orphaned snapshots to a JSON file
        
        Args:
            file_path: Path to output JSON file
        """
        if not self.orphaned_snapshots:
            logger.info("No orphaned snapshots to export")
            return
            
        try:
            with open(file_path, 'w') as f:
                json.dump({
                    'generated_at': datetime.datetime.utcnow().isoformat(),
                    'orphaned_snapshots': self.orphaned_snapshots
                }, f, indent=2)
                
            logger.info(f"Exported {len(self.orphaned_snapshots)} orphaned snapshots to {file_path}")
        except Exception as e:
            logger.error(f"Failed to export to JSON: {str(e)}")

    def print_summary(self) -> None:
        """Print a summary of the found orphaned snapshots"""
        if not self.orphaned_snapshots:
            logger.info("No orphaned snapshots found")
            return
            
        total_size_gb = sum(s['size_gb'] for s in self.orphaned_snapshots if s['size_gb'])
        
        print("\n=== Orphaned Snapshots Summary ===")
        print(f"Total orphaned snapshots: {len(self.orphaned_snapshots)}")
        print(f"Total size: {total_size_gb} GB")
        
        # Group by subscription
        by_sub = {}
        for snapshot in self.orphaned_snapshots:
            sub_name = snapshot['subscription_name']
            if sub_name not in by_sub:
                by_sub[sub_name] = []
            by_sub[sub_name].append(snapshot)
        
        print("\nBreakdown by subscription:")
        for sub_name, snapshots in by_sub.items():
            sub_size = sum(s['size_gb'] for s in snapshots if s['size_gb'])
            print(f"  - {sub_name}: {len(snapshots)} snapshots, {sub_size} GB")

    def print_snapshots(self) -> None:
        """Print details of the found orphaned snapshots in tabular format"""
        if not self.orphaned_snapshots:
            return
            
        if tabulate:
            # Create a table with key information
            table_data = []
            for snapshot in self.orphaned_snapshots:
                table_data.append([
                    snapshot['subscription_name'],
                    snapshot['resource_group'],
                    snapshot['name'],
                    snapshot['size_gb'],
                    snapshot['created_time'],
                ])
                
            headers = ["Subscription", "Resource Group", "Snapshot Name", "Size (GB)", "Created Time"]
            print("\nOrphaned Snapshots:")
            print(tabulate(table_data, headers=headers, tablefmt="grid"))
        else:
            # Fallback if tabulate is not available
            print("\nOrphaned Snapshots:")
            for i, snapshot in enumerate(self.orphaned_snapshots, 1):
                print(f"\n{i}. {snapshot['name']} ({snapshot['size_gb']} GB)")
                print(f"   Subscription: {snapshot['subscription_name']}")
                print(f"   Resource Group: {snapshot['resource_group']}")
                print(f"   Created: {snapshot['created_time']}")


def get_credential(auth_method: str, sp_client_id: str = None, sp_client_secret: str = None, sp_tenant_id: str = None):
    """
    Get Azure credential based on authentication method
    
    Args:
        auth_method: Authentication method (cli, managed-identity, service-principal)
        sp_client_id: Service principal client ID (for service-principal method)
        sp_client_secret: Service principal client secret (for service-principal method)
        sp_tenant_id: Service principal tenant ID (for service-principal method)
        
    Returns:
        Azure credential object
    """
    if auth_method == "cli":
        logger.info("Using Azure CLI authentication")
        return DefaultAzureCredential(exclude_managed_identity_credential=True)
    elif auth_method == "managed-identity":
        logger.info("Using Managed Identity authentication")
        client_id = os.environ.get("MANAGED_IDENTITY_CLIENT_ID")
        return ManagedIdentityCredential(client_id=client_id)
    elif auth_method == "service-principal":
        if not all([sp_client_id, sp_client_secret, sp_tenant_id]):
            raise ValueError("Service principal authentication requires client ID, client secret, and tenant ID")
        logger.info("Using Service Principal authentication")
        return ClientSecretCredential(sp_tenant_id, sp_client_id, sp_client_secret)
    else:
        raise ValueError(f"Unsupported authentication method: {auth_method}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Azure Snapshot Cleanup Tool - Find and manage orphaned snapshots"
    )
    
    # Authentication options
    auth_group = parser.add_argument_group("Authentication")
    auth_group.add_argument(
        "--auth-method",
        choices=["cli", "managed-identity", "service-principal"],
        default="cli",
        help="Authentication method (default: cli)"
    )
    auth_group.add_argument(
        "--sp-client-id",
        help="Service Principal Client ID (for service-principal auth)"
    )
    auth_group.add_argument(
        "--sp-client-secret",
        help="Service Principal Client Secret (for service-principal auth)"
    )
    auth_group.add_argument(
        "--sp-tenant-id",
        help="Service Principal Tenant ID (for service-principal auth)"
    )
    
    # Operation options
    parser.add_argument(
        "--subscription-id",
        help="Specific subscription ID to scan (default: scan all accessible subscriptions)"
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete orphaned snapshots (default: report only)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform a dry run (don't actually delete snapshots)"
    )
    parser.add_argument(
        "--export",
        help="Export results to a JSON file"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Set logging level (default: INFO)"
    )
    
    args = parser.parse_args()
    
    try:
        # Get credential based on authentication method
        credential = get_credential(
            args.auth_method,
            args.sp_client_id,
            args.sp_client_secret,
            args.sp_tenant_id
        )
        
        # Create snapshot manager
        snapshot_manager = AzureSnapshotManager(
            credential,
            subscription_id=args.subscription_id,
            log_level=args.log_level
        )
        
        # Find orphaned snapshots
        orphaned_snapshots = snapshot_manager.find_orphaned_snapshots()
        
        # Print summary and details
        snapshot_manager.print_summary()
        snapshot_manager.print_snapshots()
        
        # Export to JSON if requested
        if args.export:
            snapshot_manager.export_to_json(args.export)
        
        # Delete orphaned snapshots if requested
        if args.delete or args.dry_run:
            dry_run = True if args.dry_run else False
            if args.delete and not args.dry_run:
                confirmation = input("\nWARNING: This will delete orphaned snapshots. Continue? [y/N]: ")
                if confirmation.lower() != 'y':
                    logger.info("Deletion cancelled")
                    return 0
            
            success, failed = snapshot_manager.delete_orphaned_snapshots(dry_run=dry_run)
            
            print("\n=== Deletion Results ===")
            print(f"Successful: {success}")
            print(f"Failed: {failed}")
        
        return 0
        
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())