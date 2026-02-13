"""
Base resource manager — abstract base class for all cloud resource scanners.

Every provider manager (Azure snapshots, AWS EBS, GCP disks, etc.) inherits from
BaseResourceManager and implements the scan/delete/estimate_cost contract.
"""

from __future__ import annotations

import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ResourceStatus(str, Enum):
    """Status of an orphaned or wasteful resource."""

    ORPHANED = "orphaned"
    IDLE = "idle"
    ZOMBIE = "zombie"
    UNATTACHED = "unattached"
    EMPTY = "empty"
    OVERSIZED = "oversized"


class Severity(str, Enum):
    """Severity level for cost waste."""

    CRITICAL = "critical"     # >$100/month waste
    HIGH = "high"             # $50-100/month
    MEDIUM = "medium"         # $10-50/month
    LOW = "low"               # <$10/month
    INFO = "info"             # No direct cost


class CloudProvider(str, Enum):
    """Supported cloud providers."""

    AZURE = "azure"
    AWS = "aws"
    GCP = "gcp"


@dataclass
class OrphanedResource:
    """Unified representation of a wasteful or orphaned cloud resource."""

    # Identity
    provider: CloudProvider
    resource_type: str              # e.g. "snapshot", "disk", "public_ip"
    resource_id: str                # Full cloud resource ID
    name: str                       # Human-readable name
    region: str                     # Cloud region/location

    # Ownership
    subscription_or_account: str    # Azure sub ID, AWS account ID, GCP project
    subscription_name: str          # Human-friendly name
    resource_group: str = ""        # Azure RG / AWS VPC / GCP project

    # Details
    status: ResourceStatus = ResourceStatus.ORPHANED
    size_gb: float = 0.0
    estimated_monthly_cost: float = 0.0
    age_days: int = 0
    created_time: str = ""
    last_used_time: str = ""

    # Metadata
    tags: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    severity: Severity = Severity.LOW

    # Dependencies
    source_resource_id: str = ""     # Parent resource (e.g., disk for snapshot)
    dependent_resources: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Auto-compute severity from estimated monthly cost."""
        if self.estimated_monthly_cost >= 100:
            self.severity = Severity.CRITICAL
        elif self.estimated_monthly_cost >= 50:
            self.severity = Severity.HIGH
        elif self.estimated_monthly_cost >= 10:
            self.severity = Severity.MEDIUM
        elif self.estimated_monthly_cost > 0:
            self.severity = Severity.LOW
        else:
            self.severity = Severity.INFO

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "provider": self.provider.value,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "name": self.name,
            "region": self.region,
            "subscription_or_account": self.subscription_or_account,
            "subscription_name": self.subscription_name,
            "resource_group": self.resource_group,
            "status": self.status.value,
            "size_gb": self.size_gb,
            "estimated_monthly_cost": self.estimated_monthly_cost,
            "age_days": self.age_days,
            "created_time": self.created_time,
            "last_used_time": self.last_used_time,
            "tags": self.tags,
            "metadata": self.metadata,
            "severity": self.severity.value,
            "source_resource_id": self.source_resource_id,
            "dependent_resources": self.dependent_resources,
        }


@dataclass
class ScanResult:
    """Aggregated results from a resource scan."""

    provider: CloudProvider
    resource_type: str
    scan_timestamp: str = field(
        default_factory=lambda: datetime.datetime.utcnow().isoformat()
    )
    resources: List[OrphanedResource] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        return len(self.resources)

    @property
    def total_size_gb(self) -> float:
        return sum(r.size_gb for r in self.resources)

    @property
    def total_monthly_cost(self) -> float:
        return sum(r.estimated_monthly_cost for r in self.resources)

    @property
    def total_annual_savings(self) -> float:
        return self.total_monthly_cost * 12

    def summary(self) -> Dict[str, Any]:
        """Return a summary dictionary."""
        return {
            "provider": self.provider.value,
            "resource_type": self.resource_type,
            "scan_timestamp": self.scan_timestamp,
            "total_resources": self.total_count,
            "total_size_gb": round(self.total_size_gb, 2),
            "total_monthly_cost": round(self.total_monthly_cost, 2),
            "total_annual_savings": round(self.total_annual_savings, 2),
            "by_severity": self._count_by_severity(),
            "errors": self.errors,
        }

    def _count_by_severity(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for r in self.resources:
            counts[r.severity.value] = counts.get(r.severity.value, 0) + 1
        return counts

    def to_dict(self) -> Dict[str, Any]:
        """Full serialization including all resources."""
        result = self.summary()
        result["resources"] = [r.to_dict() for r in self.resources]
        return result


@dataclass
class DeleteResult:
    """Result of a deletion operation."""

    resource_id: str
    resource_name: str
    success: bool
    dry_run: bool
    error_message: str = ""


class BaseResourceManager(ABC):
    """
    Abstract base class for all cloud resource managers.

    Each provider/resource-type combination implements this interface:
    - AzureSnapshotManager, AzureDiskManager, AWSEC2Manager, etc.
    """

    @property
    @abstractmethod
    def provider(self) -> CloudProvider:
        """The cloud provider this manager handles."""
        ...

    @property
    @abstractmethod
    def resource_type(self) -> str:
        """The resource type (e.g. 'snapshot', 'disk', 'public_ip')."""
        ...

    @abstractmethod
    def scan(self) -> ScanResult:
        """
        Scan for orphaned/wasteful resources.

        Returns:
            ScanResult containing all found resources and any errors.
        """
        ...

    @abstractmethod
    def delete(self, resource_id: str, dry_run: bool = True) -> DeleteResult:
        """
        Delete a specific resource.

        Args:
            resource_id: Full cloud resource ID.
            dry_run: If True, simulate deletion without executing.

        Returns:
            DeleteResult with success/failure info.
        """
        ...

    @abstractmethod
    def estimate_cost(self, resource: OrphanedResource) -> float:
        """
        Estimate the monthly cost of a resource.

        Args:
            resource: The resource to estimate cost for.

        Returns:
            Estimated monthly cost in USD.
        """
        ...

    def delete_all(self, resources: List[OrphanedResource], dry_run: bool = True) -> List[DeleteResult]:
        """
        Delete all resources in the list.

        Args:
            resources: List of resources to delete.
            dry_run: If True, simulate deletions.

        Returns:
            List of DeleteResult objects.
        """
        results = []
        for resource in resources:
            result = self.delete(resource.resource_id, dry_run=dry_run)
            results.append(result)
        return results

    def get_scan_result(self, resources: List[OrphanedResource], errors: Optional[List[str]] = None) -> ScanResult:
        """Helper to create a ScanResult from discovered resources."""
        return ScanResult(
            provider=self.provider,
            resource_type=self.resource_type,
            resources=resources,
            errors=errors or [],
        )
