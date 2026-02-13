"""
Cross-cloud cost estimation calculator.

Provides approximate monthly cost estimates for various cloud resources
based on publicly available pricing. Costs are estimates — actual billing
may differ based on region, discounts, and reserved capacity.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Optional


class DiskTier(str, Enum):
    """Storage tier/type for disk pricing."""

    STANDARD_HDD = "standard_hdd"
    STANDARD_SSD = "standard_ssd"
    PREMIUM_SSD = "premium_ssd"
    ULTRA = "ultra"


# ── Approximate pricing tables (USD/GB/month) ─────────────────────────────────

AZURE_SNAPSHOT_COST_PER_GB = 0.05          # Managed snapshot
AZURE_DISK_COST: Dict[str, float] = {
    "standard_hdd": 0.04,
    "standard_ssd": 0.075,
    "premium_ssd": 0.132,
    "ultra": 0.40,
}
AZURE_PUBLIC_IP_COST = 3.65                # Static public IP (unused), per month
AZURE_LB_BASIC_COST = 0.0                  # Basic LB is free
AZURE_LB_STANDARD_COST = 18.25            # Standard LB per month (base)

AWS_EBS_COST: Dict[str, float] = {
    "gp2": 0.10,
    "gp3": 0.08,
    "io1": 0.125,
    "io2": 0.125,
    "st1": 0.045,
    "sc1": 0.015,
    "standard": 0.05,
}
AWS_SNAPSHOT_COST_PER_GB = 0.05
AWS_ELASTIC_IP_COST = 3.65                 # Unused EIP (since Feb 2024)
AWS_ELB_COST = 16.43                       # ALB/NLB per month (base)

GCP_DISK_COST: Dict[str, float] = {
    "pd-standard": 0.04,
    "pd-balanced": 0.10,
    "pd-ssd": 0.17,
    "pd-extreme": 0.125,
}
GCP_SNAPSHOT_COST_PER_GB = 0.026
GCP_STATIC_IP_COST = 7.30                 # Unused static external IP


class CostCalculator:
    """
    Estimate monthly costs for cloud resources.

    All costs are approximate and based on US regions.
    """

    # ── Azure ──────────────────────────────────────────────────────────────

    @staticmethod
    def azure_snapshot(size_gb: float) -> float:
        """Estimate monthly cost of an Azure managed snapshot."""
        return round(size_gb * AZURE_SNAPSHOT_COST_PER_GB, 2)

    @staticmethod
    def azure_disk(size_gb: float, tier: str = "standard_hdd") -> float:
        """Estimate monthly cost of an Azure managed disk."""
        cost_per_gb = AZURE_DISK_COST.get(tier.lower(), AZURE_DISK_COST["standard_hdd"])
        return round(size_gb * cost_per_gb, 2)

    @staticmethod
    def azure_public_ip() -> float:
        """Monthly cost of an unused Azure public IP."""
        return AZURE_PUBLIC_IP_COST

    @staticmethod
    def azure_load_balancer(standard: bool = True) -> float:
        """Monthly base cost of an Azure load balancer."""
        return AZURE_LB_STANDARD_COST if standard else AZURE_LB_BASIC_COST

    # ── AWS ────────────────────────────────────────────────────────────────

    @staticmethod
    def aws_ebs_volume(size_gb: float, volume_type: str = "gp3") -> float:
        """Estimate monthly cost of an AWS EBS volume."""
        cost_per_gb = AWS_EBS_COST.get(volume_type.lower(), AWS_EBS_COST["gp3"])
        return round(size_gb * cost_per_gb, 2)

    @staticmethod
    def aws_snapshot(size_gb: float) -> float:
        """Estimate monthly cost of an AWS EBS snapshot."""
        return round(size_gb * AWS_SNAPSHOT_COST_PER_GB, 2)

    @staticmethod
    def aws_elastic_ip() -> float:
        """Monthly cost of an unused AWS Elastic IP."""
        return AWS_ELASTIC_IP_COST

    @staticmethod
    def aws_load_balancer() -> float:
        """Monthly base cost of an AWS ALB/NLB."""
        return AWS_ELB_COST

    # ── GCP ────────────────────────────────────────────────────────────────

    @staticmethod
    def gcp_disk(size_gb: float, disk_type: str = "pd-standard") -> float:
        """Estimate monthly cost of a GCP persistent disk."""
        cost_per_gb = GCP_DISK_COST.get(disk_type.lower(), GCP_DISK_COST["pd-standard"])
        return round(size_gb * cost_per_gb, 2)

    @staticmethod
    def gcp_snapshot(size_gb: float) -> float:
        """Estimate monthly cost of a GCP disk snapshot."""
        return round(size_gb * GCP_SNAPSHOT_COST_PER_GB, 2)

    @staticmethod
    def gcp_static_ip() -> float:
        """Monthly cost of an unused GCP static external IP."""
        return GCP_STATIC_IP_COST

    # ── Cross-cloud summary ───────────────────────────────────────────────

    @staticmethod
    def total_savings_summary(resources: list) -> Dict[str, float]:
        """
        Compute aggregate savings from a list of OrphanedResource objects.

        Args:
            resources: List of OrphanedResource instances.

        Returns:
            Dict with monthly_savings, annual_savings, and per-provider breakdown.
        """
        total_monthly = sum(r.estimated_monthly_cost for r in resources)
        by_provider: Dict[str, float] = {}

        for r in resources:
            provider = r.provider.value if hasattr(r.provider, "value") else str(r.provider)
            by_provider[provider] = by_provider.get(provider, 0.0) + r.estimated_monthly_cost

        return {
            "monthly_savings": round(total_monthly, 2),
            "annual_savings": round(total_monthly * 12, 2),
            "by_provider": {k: round(v, 2) for k, v in by_provider.items()},
        }
