"""
Smart Recommender — generates actionable right-sizing and optimization recommendations.

Uses resource metrics and patterns to suggest:
- Right-sizing (VM, disk) based on actual usage
- Reserved Instance / Savings Plan purchases
- Resource cleanup priorities
- Architecture optimizations
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List

logger = logging.getLogger("finops-ai.ml.recommender")


class RecommendationType(str, Enum):
    """Types of cost-saving recommendations."""

    DELETE = "delete"
    DOWNSIZE = "downsize"
    RESERVE = "reserve"
    MIGRATE = "migrate"
    TAG = "tag"
    SCHEDULE = "schedule"
    ARCHIVE = "archive"


class Priority(str, Enum):
    """Recommendation priority."""

    CRITICAL = "critical"  # >$1000/mo savings
    HIGH = "high"          # >$100/mo savings
    MEDIUM = "medium"      # >$10/mo savings
    LOW = "low"            # <$10/mo savings


@dataclass
class Recommendation:
    """A single optimization recommendation."""

    resource_id: str
    resource_name: str
    provider: str
    recommendation_type: RecommendationType
    priority: Priority
    title: str
    description: str
    estimated_monthly_savings: float
    estimated_annual_savings: float = 0.0
    implementation_effort: str = "low"  # low, medium, high
    risk_level: str = "low"  # low, medium, high
    action_steps: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.estimated_annual_savings = round(self.estimated_monthly_savings * 12, 2)


@dataclass
class RecommendationReport:
    """Summary report of all recommendations."""

    total_recommendations: int = 0
    total_monthly_savings: float = 0.0
    total_annual_savings: float = 0.0
    recommendations: List[Recommendation] = field(default_factory=list)
    by_provider: Dict[str, float] = field(default_factory=dict)
    by_type: Dict[str, int] = field(default_factory=dict)


class SmartRecommender:
    """
    Generates contextual recommendations based on resource analysis.

    Analyzes orphaned resources, usage patterns, and costs to produce
    prioritized, actionable recommendations.
    """

    def analyze(self, resources: list) -> RecommendationReport:
        """
        Analyze resources and generate recommendations.

        Args:
            resources: List of OrphanedResource instances.

        Returns:
            RecommendationReport with prioritized recommendations.
        """
        recommendations: List[Recommendation] = []

        for resource in resources:
            recs = self._generate_recommendations(resource)
            recommendations.extend(recs)

        # Sort by savings (highest first)
        recommendations.sort(key=lambda r: r.estimated_monthly_savings, reverse=True)

        # Build summary
        total_monthly = sum(r.estimated_monthly_savings for r in recommendations)
        by_provider: Dict[str, float] = {}
        by_type: Dict[str, int] = {}

        for rec in recommendations:
            by_provider[rec.provider] = by_provider.get(rec.provider, 0) + rec.estimated_monthly_savings
            by_type[rec.recommendation_type.value] = by_type.get(rec.recommendation_type.value, 0) + 1

        return RecommendationReport(
            total_recommendations=len(recommendations),
            total_monthly_savings=round(total_monthly, 2),
            total_annual_savings=round(total_monthly * 12, 2),
            recommendations=recommendations,
            by_provider={k: round(v, 2) for k, v in by_provider.items()},
            by_type=by_type,
        )

    def _generate_recommendations(self, resource: Any) -> List[Recommendation]:
        """Generate recommendations for a single resource."""
        recs: List[Recommendation] = []
        provider = resource.provider.value if hasattr(resource.provider, "value") else str(resource.provider)
        cost = resource.estimated_monthly_cost
        status = resource.status.value if hasattr(resource.status, "value") else str(resource.status)

        # Priority based on cost
        if cost >= 1000:
            priority = Priority.CRITICAL
        elif cost >= 100:
            priority = Priority.HIGH
        elif cost >= 10:
            priority = Priority.MEDIUM
        else:
            priority = Priority.LOW

        # ── Delete recommendation for orphaned/unattached resources ────
        if status in ("orphaned", "unattached", "empty"):
            recs.append(Recommendation(
                resource_id=resource.resource_id,
                resource_name=resource.name,
                provider=provider,
                recommendation_type=RecommendationType.DELETE,
                priority=priority,
                title=f"Delete {status} {resource.resource_type}: {resource.name}",
                description=(
                    f"This {resource.resource_type} is {status} and costs "
                    f"${cost:.2f}/month. It can be safely deleted."
                ),
                estimated_monthly_savings=cost,
                risk_level="low",
                action_steps=[
                    f"Verify {resource.name} is not needed",
                    f"Run: finops-ai delete --resource-id '{resource.resource_id}'",
                    "Confirm deletion in cloud console",
                ],
            ))

        # ── Zombie VM recommendations ──────────────────────────────────
        if status == "zombie":
            recs.append(Recommendation(
                resource_id=resource.resource_id,
                resource_name=resource.name,
                provider=provider,
                recommendation_type=RecommendationType.DELETE,
                priority=priority,
                title=f"Terminate zombie VM: {resource.name}",
                description=(
                    f"VM {resource.name} has been stopped for {resource.age_days} days. "
                    f"Even stopped, it incurs ${cost:.2f}/mo in disk costs."
                ),
                estimated_monthly_savings=cost,
                risk_level="medium",
                action_steps=[
                    "Verify no data recovery is needed",
                    "Snapshot any important disks",
                    f"Terminate: finops-ai delete --resource-id '{resource.resource_id}'",
                ],
            ))

        # ── Tagging recommendation ─────────────────────────────────────
        if not resource.tags:
            recs.append(Recommendation(
                resource_id=resource.resource_id,
                resource_name=resource.name,
                provider=provider,
                recommendation_type=RecommendationType.TAG,
                priority=Priority.LOW,
                title=f"Add tags to {resource.resource_type}: {resource.name}",
                description="Untagged resources are harder to manage and audit.",
                estimated_monthly_savings=0.0,
                implementation_effort="low",
                risk_level="low",
                action_steps=[
                    "Add 'Owner', 'Environment', and 'Project' tags",
                    "Set up tag enforcement policies",
                ],
            ))

        # ── Archive recommendation for old snapshots ───────────────────
        if resource.resource_type in ("snapshot", "ebs_snapshot") and resource.age_days > 365:
            recs.append(Recommendation(
                resource_id=resource.resource_id,
                resource_name=resource.name,
                provider=provider,
                recommendation_type=RecommendationType.ARCHIVE,
                priority=Priority.MEDIUM,
                title=f"Archive old snapshot: {resource.name}",
                description=(
                    f"Snapshot is {resource.age_days} days old. "
                    f"Consider archiving to cheaper storage tier."
                ),
                estimated_monthly_savings=round(cost * 0.5, 2),  # ~50% savings from archive
                risk_level="low",
                action_steps=[
                    "Move to archive storage tier",
                    "Or delete if no longer needed",
                ],
            ))

        return recs
