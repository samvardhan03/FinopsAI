"""
AWS EC2 Manager — find stopped instances and unused security groups.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from finops_ai.core.base_manager import (
    BaseResourceManager,
    CloudProvider,
    DeleteResult,
    OrphanedResource,
    ResourceStatus,
    ScanResult,
)

logger = logging.getLogger("finops-ai.aws.ec2")


class AWSEC2Manager(BaseResourceManager):
    """Detects stopped EC2 instances (zombies) and unused security groups."""

    def __init__(
        self,
        session: Any,
        regions: Optional[List[str]] = None,
        zombie_days: int = 30,
    ) -> None:
        try:
            import boto3
        except ImportError:
            raise ImportError("AWS SDK not installed. Install with: pip install finops-ai[aws]")

        self.session = session
        self.regions = regions or ["us-east-1"]
        self.zombie_days = zombie_days
        self._account_id: Optional[str] = None

    @property
    def provider(self) -> CloudProvider:
        return CloudProvider.AWS

    @property
    def resource_type(self) -> str:
        return "ec2"

    def _get_account_id(self) -> str:
        if not self._account_id:
            sts = self.session.client("sts")
            self._account_id = sts.get_caller_identity()["Account"]
        return self._account_id

    def scan(self) -> ScanResult:
        """Scan for stopped EC2 instances and unused security groups."""
        resources: List[OrphanedResource] = []
        errors: List[str] = []
        account_id = self._get_account_id()

        for region in self.regions:
            logger.info(f"Scanning EC2 in {region}")
            try:
                ec2 = self.session.client("ec2", region_name=region)

                # ── Stopped instances ──────────────────────────────────
                response = ec2.describe_instances(
                    Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}]
                )
                for reservation in response.get("Reservations", []):
                    for instance in reservation.get("Instances", []):
                        instance_id = instance["InstanceId"]
                        launch_time = instance.get("LaunchTime")
                        age_days = 0
                        created_str = ""

                        if launch_time:
                            if launch_time.tzinfo is None:
                                launch_time = launch_time.replace(tzinfo=timezone.utc)
                            age_days = (datetime.now(timezone.utc) - launch_time).days
                            created_str = launch_time.strftime("%Y-%m-%d %H:%M:%S UTC")

                        if age_days >= self.zombie_days:
                            # Get name from tags
                            name = instance_id
                            tags_dict: Dict[str, str] = {}
                            for tag in instance.get("Tags", []):
                                tags_dict[tag["Key"]] = tag["Value"]
                                if tag["Key"] == "Name":
                                    name = tag["Value"]

                            instance_type = instance.get("InstanceType", "unknown")

                            # Estimate EBS costs (stopped instances still pay for EBS)
                            ebs_cost = 0.0
                            for bdm in instance.get("BlockDeviceMappings", []):
                                ebs = bdm.get("Ebs", {})
                                vol_id = ebs.get("VolumeId")
                                if vol_id:
                                    try:
                                        vol_resp = ec2.describe_volumes(VolumeIds=[vol_id])
                                        for vol in vol_resp.get("Volumes", []):
                                            size = vol.get("Size", 0)
                                            vol_type = vol.get("VolumeType", "gp3")
                                            from finops_ai.utils.cost_calculator import CostCalculator
                                            ebs_cost += CostCalculator.aws_ebs_volume(size, vol_type)
                                    except Exception:
                                        ebs_cost += 8.0  # default gp3 100GB

                            resources.append(OrphanedResource(
                                provider=CloudProvider.AWS,
                                resource_type="ec2_instance",
                                resource_id=f"arn:aws:ec2:{region}:{account_id}:instance/{instance_id}",
                                name=name,
                                region=region,
                                subscription_or_account=account_id,
                                subscription_name=f"AWS Account {account_id}",
                                status=ResourceStatus.ZOMBIE,
                                estimated_monthly_cost=ebs_cost,
                                age_days=age_days,
                                created_time=created_str,
                                tags=tags_dict,
                                metadata={
                                    "instance_type": instance_type,
                                    "instance_id": instance_id,
                                    "state": "stopped",
                                },
                            ))

                # ── Unused Security Groups ─────────────────────────────
                sgs = ec2.describe_security_groups()
                enis = ec2.describe_network_interfaces()

                # Build set of SGs in use
                used_sgs = set()
                for eni in enis.get("NetworkInterfaces", []):
                    for sg in eni.get("Groups", []):
                        used_sgs.add(sg["GroupId"])

                for sg in sgs.get("SecurityGroups", []):
                    sg_id = sg["GroupId"]
                    sg_name = sg.get("GroupName", sg_id)

                    if sg_name == "default":
                        continue  # Skip default SG

                    if sg_id not in used_sgs:
                        tags_dict = {t["Key"]: t["Value"] for t in sg.get("Tags", [])}
                        resources.append(OrphanedResource(
                            provider=CloudProvider.AWS,
                            resource_type="security_group",
                            resource_id=f"arn:aws:ec2:{region}:{account_id}:security-group/{sg_id}",
                            name=sg_name,
                            region=region,
                            subscription_or_account=account_id,
                            subscription_name=f"AWS Account {account_id}",
                            status=ResourceStatus.IDLE,
                            estimated_monthly_cost=0.0,
                            tags=tags_dict,
                            metadata={"group_id": sg_id, "vpc_id": sg.get("VpcId", "")},
                        ))

            except Exception as e:
                error_msg = f"Error scanning EC2 in {region}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        logger.info(f"Found {len(resources)} EC2 resources to review")
        return self.get_scan_result(resources, errors)

    def delete(self, resource_id: str, dry_run: bool = True) -> DeleteResult:
        """Terminate an EC2 instance or delete a security group."""
        # Parse ARN to get region and resource type
        parts = resource_id.split(":")
        resource_name = resource_id.split("/")[-1]

        if dry_run:
            logger.info(f"DRY RUN: Would delete {resource_id}")
            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=True, dry_run=True)

        try:
            region = parts[3] if len(parts) > 3 else "us-east-1"
            ec2 = self.session.client("ec2", region_name=region)

            if "instance/" in resource_id:
                instance_id = resource_id.split("/")[-1]
                ec2.terminate_instances(InstanceIds=[instance_id])
            elif "security-group/" in resource_id:
                sg_id = resource_id.split("/")[-1]
                ec2.delete_security_group(GroupId=sg_id)

            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=True, dry_run=False)
        except Exception as e:
            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=False, dry_run=False, error_message=str(e))

    def estimate_cost(self, resource: OrphanedResource) -> float:
        return resource.estimated_monthly_cost
