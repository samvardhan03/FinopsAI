"""
AWS Network Manager — find unused Elastic IPs, idle ELBs, and orphaned VPC resources.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from finops_ai.core.base_manager import (
    BaseResourceManager,
    CloudProvider,
    DeleteResult,
    OrphanedResource,
    ResourceStatus,
    ScanResult,
)
from finops_ai.utils.cost_calculator import CostCalculator

logger = logging.getLogger("finops-ai.aws.network")


class AWSNetworkManager(BaseResourceManager):
    """Finds unused AWS network resources: Elastic IPs, idle load balancers."""

    def __init__(self, session: Any, regions: Optional[List[str]] = None) -> None:
        try:
            import boto3
        except ImportError:
            raise ImportError("AWS SDK not installed. Install with: pip install finops-ai[aws]")

        self.session = session
        self.regions = regions or ["us-east-1"]
        self._account_id: Optional[str] = None

    @property
    def provider(self) -> CloudProvider:
        return CloudProvider.AWS

    @property
    def resource_type(self) -> str:
        return "network"

    def _get_account_id(self) -> str:
        if not self._account_id:
            sts = self.session.client("sts")
            self._account_id = sts.get_caller_identity()["Account"]
        return self._account_id

    def scan(self) -> ScanResult:
        resources: List[OrphanedResource] = []
        errors: List[str] = []
        account_id = self._get_account_id()

        for region in self.regions:
            logger.info(f"Scanning network resources in AWS {region}")
            try:
                ec2 = self.session.client("ec2", region_name=region)
                elbv2 = self.session.client("elbv2", region_name=region)

                # ── Unassociated Elastic IPs ───────────────────────────
                eips = ec2.describe_addresses()
                for eip in eips.get("Addresses", []):
                    if not eip.get("AssociationId"):
                        alloc_id = eip.get("AllocationId", "")
                        ip_addr = eip.get("PublicIp", "unknown")
                        tags = {t["Key"]: t["Value"] for t in eip.get("Tags", [])}

                        resources.append(OrphanedResource(
                            provider=CloudProvider.AWS,
                            resource_type="elastic_ip",
                            resource_id=f"arn:aws:ec2:{region}:{account_id}:eip/{alloc_id}",
                            name=tags.get("Name", ip_addr),
                            region=region,
                            subscription_or_account=account_id,
                            subscription_name=f"AWS Account {account_id}",
                            status=ResourceStatus.UNATTACHED,
                            estimated_monthly_cost=CostCalculator.aws_elastic_ip(),
                            tags=tags,
                            metadata={"public_ip": ip_addr, "allocation_id": alloc_id},
                        ))

                # ── Idle ELBs/ALBs ─────────────────────────────────────
                lbs = elbv2.describe_load_balancers()
                for lb in lbs.get("LoadBalancers", []):
                    lb_arn = lb["LoadBalancerArn"]
                    lb_name = lb.get("LoadBalancerName", "unknown")

                    # Check target groups
                    tgs = elbv2.describe_target_groups(LoadBalancerArn=lb_arn)
                    has_targets = False
                    for tg in tgs.get("TargetGroups", []):
                        health = elbv2.describe_target_health(TargetGroupArn=tg["TargetGroupArn"])
                        if health.get("TargetHealthDescriptions"):
                            has_targets = True
                            break

                    if not has_targets:
                        tags_resp = elbv2.describe_tags(ResourceArns=[lb_arn])
                        tags = {}
                        for td in tags_resp.get("TagDescriptions", []):
                            tags = {t["Key"]: t["Value"] for t in td.get("Tags", [])}

                        resources.append(OrphanedResource(
                            provider=CloudProvider.AWS,
                            resource_type="load_balancer",
                            resource_id=lb_arn,
                            name=lb_name,
                            region=region,
                            subscription_or_account=account_id,
                            subscription_name=f"AWS Account {account_id}",
                            status=ResourceStatus.IDLE,
                            estimated_monthly_cost=CostCalculator.aws_load_balancer(),
                            tags=tags,
                            metadata={
                                "type": lb.get("Type", "application"),
                                "scheme": lb.get("Scheme", ""),
                                "dns": lb.get("DNSName", ""),
                            },
                        ))

            except Exception as e:
                error_msg = f"Error scanning AWS network in {region}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        logger.info(f"Found {len(resources)} unused AWS network resources")
        return self.get_scan_result(resources, errors)

    def delete(self, resource_id: str, dry_run: bool = True) -> DeleteResult:
        resource_name = resource_id.split("/")[-1]

        if dry_run:
            logger.info(f"DRY RUN: Would delete {resource_id}")
            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=True, dry_run=True)

        try:
            parts = resource_id.split(":")
            region = parts[3] if len(parts) > 3 else "us-east-1"

            if "eip/" in resource_id:
                ec2 = self.session.client("ec2", region_name=region)
                ec2.release_address(AllocationId=resource_name)
            elif "loadbalancer/" in resource_id:
                elbv2 = self.session.client("elbv2", region_name=region)
                elbv2.delete_load_balancer(LoadBalancerArn=resource_id)

            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=True, dry_run=False)
        except Exception as e:
            return DeleteResult(resource_id=resource_id, resource_name=resource_name,
                                success=False, dry_run=False, error_message=str(e))

    def estimate_cost(self, resource: OrphanedResource) -> float:
        if resource.resource_type == "elastic_ip":
            return CostCalculator.aws_elastic_ip()
        elif resource.resource_type == "load_balancer":
            return CostCalculator.aws_load_balancer()
        return 0.0
