"""
AWS provider — resource managers for detecting waste across AWS services.

Available managers:
- AWSEC2Manager: Stopped instances, unused security groups
- AWSEBSManager: Unattached volumes, orphaned snapshots
- AWSNetworkManager: Elastic IPs, idle ELBs, orphaned VPCs
- AWSRDSManager: Unused RDS snapshots
"""

from finops_ai.providers import register_manager

_MANAGERS_REGISTERED = False


def _register_all() -> None:
    global _MANAGERS_REGISTERED
    if _MANAGERS_REGISTERED:
        return

    try:
        from finops_ai.providers.aws.ec2_manager import AWSEC2Manager
        from finops_ai.providers.aws.ebs_manager import AWSEBSManager
        from finops_ai.providers.aws.network_manager import AWSNetworkManager
        from finops_ai.providers.aws.rds_manager import AWSRDSManager

        for mgr in [AWSEC2Manager, AWSEBSManager, AWSNetworkManager, AWSRDSManager]:
            register_manager("aws", mgr)

        _MANAGERS_REGISTERED = True
    except ImportError:
        pass
