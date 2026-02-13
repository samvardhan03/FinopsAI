"""
Azure provider — resource managers for Azure cloud resources.

Available managers:
- AzureSnapshotManager: Orphaned managed snapshots
- AzureDiskManager: Unattached managed disks
- AzureNetworkManager: Unused IPs, NICs, load balancers, VNets
- AzureVMManager: Zombie VMs (stopped > N days)
- AzureStorageManager: Orphaned blob containers
- AzureAppServiceManager: Unused App Service Plans
- AzureResourceGroupManager: Empty resource groups
"""

from finops_ai.providers import register_manager

# Lazy imports to avoid requiring azure SDK at import time
_MANAGERS_REGISTERED = False


def _register_all() -> None:
    global _MANAGERS_REGISTERED
    if _MANAGERS_REGISTERED:
        return

    try:
        from finops_ai.providers.azure.snapshot_manager import AzureSnapshotManager
        from finops_ai.providers.azure.disk_manager import AzureDiskManager
        from finops_ai.providers.azure.network_manager import AzureNetworkManager
        from finops_ai.providers.azure.vm_manager import AzureVMManager
        from finops_ai.providers.azure.storage_manager import AzureStorageManager
        from finops_ai.providers.azure.app_service_manager import AzureAppServiceManager
        from finops_ai.providers.azure.resource_group_manager import AzureResourceGroupManager

        for mgr in [
            AzureSnapshotManager,
            AzureDiskManager,
            AzureNetworkManager,
            AzureVMManager,
            AzureStorageManager,
            AzureAppServiceManager,
            AzureResourceGroupManager,
        ]:
            register_manager("azure", mgr)

        _MANAGERS_REGISTERED = True
    except ImportError:
        pass  # Azure SDK not installed
