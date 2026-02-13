"""
GCP provider — resource managers for detecting waste across Google Cloud.

Available managers:
- GCPComputeManager: Stopped VMs, unattached disks, orphaned snapshots
- GCPNetworkManager: Unused static IPs, idle forwarding rules
- GCPStorageManager: Idle storage buckets
"""

from finops_ai.providers import register_manager

_MANAGERS_REGISTERED = False


def _register_all() -> None:
    global _MANAGERS_REGISTERED
    if _MANAGERS_REGISTERED:
        return

    try:
        from finops_ai.providers.gcp.compute_manager import GCPComputeManager
        from finops_ai.providers.gcp.network_manager import GCPNetworkManager
        from finops_ai.providers.gcp.storage_manager import GCPStorageManager

        for mgr in [GCPComputeManager, GCPNetworkManager, GCPStorageManager]:
            register_manager("gcp", mgr)

        _MANAGERS_REGISTERED = True
    except ImportError:
        pass
