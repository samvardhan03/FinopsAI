import azure.functions as func
import datetime
import json
import logging
import os

from azure.identity import ManagedIdentityCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.resource import ResourceManagementClient, SubscriptionClient
from azure.core.exceptions import AzureError
from azure.storage.blob import BlobServiceClient


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

    def get_subscriptions(self):
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

    def _get_compute_client(self, subscription_id: str):
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

    def _get_resource_client(self, subscription_id: str):
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

    def disk_exists(self, subscription_id: str, source_resource_id: str):
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

    def find_orphaned_snapshots(self):
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

    def delete_orphaned_snapshots(self, dry_run=True):
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

    def export_to_storage(self, connection_string, container_name):
        """
        Export orphaned snapshots report to Azure Blob Storage
        
        Args:
            connection_string: Storage account connection string
            container_name: Storage container name
            
        Returns:
            Blob URL if successful, None if failed
        """
        if not self.orphaned_snapshots:
            logging.info("No orphaned snapshots to export")
            return None
            
        try:
            # Create blob service client
            blob_service_client = BlobServiceClient.from_connection_string(connection_string)
            
            # Get container client
            container_client = blob_service_client.get_container_client(container_name)
            
            # Create container if it doesn't exist
            if not container_client.exists():
                container_client.create_container()
            
            # Create a unique blob name with timestamp
            timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            blob_name = f"orphaned_snapshots_{timestamp}.json"
            
            # Get blob client
            blob_client = container_client.get_blob_client(blob_name)
            
            # Create JSON content
            json_content = json.dumps({
                'generated_at': datetime.datetime.utcnow().isoformat(),
                'orphaned_snapshots': self.orphaned_snapshots
            }, indent=2)
            
            # Upload JSON content
            blob_client.upload_blob(json_content, overwrite=True)
            
            logging.info(f"Exported {len(self.orphaned_snapshots)} orphaned snapshots to blob: {blob_name}")
            
            return blob_client.url
            
        except Exception as e:
            logging.error(f"Failed to export to blob storage: {str(e)}")
            return None


def main(req: func.HttpRequest) -> func.HttpResponse:
    """
    Azure Function entry point
    
    Args:
        req: HTTP request object
        
    Returns:
        HTTP response object
    """
    logging.info('Python HTTP trigger function processed a request.')
    
    try:
        # Get parameters
        subscription_id = os.environ.get("SUBSCRIPTION_ID")
        managed_identity_client_id = os.environ.get("MANAGED_IDENTITY_CLIENT_ID")
        enable_deletion = os.environ.get("ENABLE_DELETION", "false").lower() == "true"
        dry_run = os.environ.get("DRY_RUN", "true").lower() == "true"
        log_level = os.environ.get("LOG_LEVEL", "INFO")
        storage_connection_string = os.environ.get("STORAGE_CONNECTION_STRING")
        storage_container_name = os.environ.get("STORAGE_CONTAINER_NAME", "snapshot-reports")
        
        # Get parameters from request if specified
        req_body = req.get_json() if req.get_body() else {}
        subscription_id = req_body.get("subscriptionId", subscription_id) 
        enable_deletion = req_body.get("enableDeletion", enable_deletion)
        dry_run = req_body.get("dryRun", dry_run)
        
        # Create managed identity credential
        credential = ManagedIdentityCredential(client_id=managed_identity_client_id)
        
        # Create snapshot manager
        snapshot_manager = AzureSnapshotManager(
            credential,
            subscription_id=subscription_id,
            log_level=log_level
        )
        
        # Find orphaned snapshots
        orphaned_snapshots = snapshot_manager.find_orphaned_snapshots()
        
        # Results
        results = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "orphanedSnapshotsCount": len(orphaned_snapshots),
            "totalSizeGB": sum(s['size_gb'] for s in orphaned_snapshots if s['size_gb']),
            "subscriptionId": subscription_id if subscription_id else "all"
        }
        
        # Delete snapshots if enabled
        if enable_deletion or not dry_run:
            successful, failed = snapshot_manager.delete_orphaned_snapshots(dry_run=dry_run)
            results["deletion"] = {
                "dryRun": dry_run,
                "successful": successful,
                "failed": failed
            }
        
        # Export report to blob storage if connection string is provided
        if storage_connection_string and storage_container_name:
            report_url = snapshot_manager.export_to_storage(
                storage_connection_string,
                storage_container_name
            )
            
            if report_url:
                results["reportUrl"] = report_url
        
        # Return results
        return func.HttpResponse(
            json.dumps(results, indent=2),
            mimetype="application/json",
            status_code=200
        )
        
    except Exception as e:
        error_message = f"Error in snapshot cleanup function: {str(e)}"
        logging.error(error_message)
        
        return func.HttpResponse(
            json.dumps({"error": error_message}),
            mimetype="application/json",
            status_code=500
        )