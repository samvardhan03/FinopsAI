import logging
import os
import datetime
import json
from typing import Dict, List, Tuple, Optional, Any

from azure.identity import DefaultAzureCredential, ManagedIdentityCredential, ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.resource import ResourceManagementClient, SubscriptionClient
from azure.core.exceptions import AzureError

# AzureSnapshotManager class for function app
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
        logging.getLogger().setLevel(getattr(logging, log_level))
        
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
            logging.info(f"Using specific subscription: {self.specific_subscription_id}")
            subscription_detail = self.subscription_client.subscriptions.get(self.specific_subscription_id)
            subscriptions = [{
                'id': subscription_detail.subscription_id,
                'name': subscription_detail.display_name
            }]
        else:
            logging.info("Getting list of accessible subscriptions")
            subscription_list = list(self.subscription_client.subscriptions.list())
            subscriptions = [{'id': sub.subscription_id, 'name': sub.display_name} for sub in subscription_list]
            
        logging.info(f"Found {len(subscriptions)} accessible subscription(s)")
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
            logging.warning(f"Invalid disk resource ID format: {source_resource_id}")
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
            logging.info(f"Scanning snapshots in subscription: {subscription['name']} ({sub_id})")
            
            compute_client = self._get_compute_client(sub_id)
            
            # Get all snapshots in the subscription
            try:
                snapshots = list(compute_client.snapshots.list())
                logging.info(f"Found {len(snapshots)} snapshots in subscription")
                
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
                logging.error(f"Error scanning snapshots in subscription {sub_id}: {str(e)}")
                
        logging.info(f"Found {len(self.orphaned_snapshots)} orphaned snapshots across all subscriptions")
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
            logging.info("No orphaned snapshots to delete")
            return (0, 0)
            
        successful = 0
        failed = 0
        
        for snapshot in self.orphaned_snapshots:
            sub_id = snapshot['subscription_id']
            resource_group = snapshot['resource_group']
            snapshot_name = snapshot['name']
            
            try:
                if dry_run:
                    logging.info(f"DRY RUN: Would delete snapshot {snapshot_name} in {resource_group}")
                    successful += 1
                else:
                    logging.info(f"Deleting snapshot {snapshot_name} in {resource_group}")
                    compute_client = self._get_compute_client(sub_id)
                    
                    # Start the deletion operation
                    delete_operation = compute_client.snapshots.begin_delete(
                        resource_group,
                        snapshot_name
                    )
                    
                    # Wait for the operation to complete
                    delete_operation.wait()
                    
                    logging.info(f"Successfully deleted snapshot {snapshot_name}")
                    successful += 1
            except AzureError as e:
                logging.error(f"Failed to delete snapshot {snapshot_name}: {str(e)}")
                failed += 1
                
        return (successful, failed)
