"""
Unit tests for FinOps AI core components.
"""

from __future__ import annotations

import pytest
from finops_ai.core.base_manager import (
    CloudProvider,
    DeleteResult,
    OrphanedResource,
    ResourceStatus,
    ScanResult,
    Severity,
)
from finops_ai.utils.cost_calculator import CostCalculator


# ── OrphanedResource Tests ─────────────────────────────────────────────────────


class TestOrphanedResource:
    """Test the OrphanedResource dataclass."""

    def _make_resource(self, **kwargs):
        defaults = dict(
            provider=CloudProvider.AZURE,
            resource_type="snapshot",
            resource_id="/subscriptions/abc/resourceGroups/rg1/providers/Microsoft.Compute/snapshots/snap1",
            name="test-snapshot",
            region="eastus",
            subscription_or_account="abc",
            subscription_name="Test Sub",
        )
        defaults.update(kwargs)
        return OrphanedResource(**defaults)

    def test_default_severity_low(self):
        r = self._make_resource(estimated_monthly_cost=5.0)
        assert r.severity == Severity.LOW

    def test_severity_medium(self):
        r = self._make_resource(estimated_monthly_cost=25.0)
        assert r.severity == Severity.MEDIUM

    def test_severity_high(self):
        r = self._make_resource(estimated_monthly_cost=60.0)
        assert r.severity == Severity.HIGH

    def test_severity_critical(self):
        r = self._make_resource(estimated_monthly_cost=150.0)
        assert r.severity == Severity.CRITICAL

    def test_default_status(self):
        r = self._make_resource()
        assert r.status == ResourceStatus.ORPHANED

    def test_tags_default_empty(self):
        r = self._make_resource()
        assert r.tags == {}

    def test_dependent_resources_default_empty(self):
        r = self._make_resource()
        assert r.dependent_resources == []


# ── CostCalculator Tests ──────────────────────────────────────────────────────


class TestCostCalculator:
    """Test the CostCalculator."""

    def test_azure_snapshot_cost(self):
        cost = CostCalculator.azure_snapshot(100)
        assert cost == 5.0  # 100 * 0.05

    def test_azure_disk_standard_hdd(self):
        cost = CostCalculator.azure_disk(100, "standard_hdd")
        assert cost == 4.0  # 100 * 0.04

    def test_azure_disk_premium_ssd(self):
        cost = CostCalculator.azure_disk(100, "premium_ssd")
        assert cost == 13.2  # 100 * 0.132

    def test_azure_public_ip(self):
        assert CostCalculator.azure_public_ip() == 3.65

    def test_azure_load_balancer_standard(self):
        assert CostCalculator.azure_load_balancer(standard=True) == 18.25

    def test_azure_load_balancer_basic(self):
        assert CostCalculator.azure_load_balancer(standard=False) == 0.0

    def test_aws_ebs_gp3(self):
        cost = CostCalculator.aws_ebs_volume(100, "gp3")
        assert cost == 8.0  # 100 * 0.08

    def test_aws_snapshot(self):
        cost = CostCalculator.aws_snapshot(100)
        assert cost == 5.0  # 100 * 0.05

    def test_aws_elastic_ip(self):
        assert CostCalculator.aws_elastic_ip() == 3.65

    def test_gcp_disk_pd_standard(self):
        cost = CostCalculator.gcp_disk(100, "pd-standard")
        assert cost == 4.0  # 100 * 0.04

    def test_gcp_snapshot(self):
        cost = CostCalculator.gcp_snapshot(100)
        assert cost == 2.6  # 100 * 0.026

    def test_gcp_static_ip(self):
        assert CostCalculator.gcp_static_ip() == 7.30

    def test_total_savings_summary(self):
        resources = [
            self._mock_resource("azure", 10.0),
            self._mock_resource("azure", 20.0),
            self._mock_resource("aws", 15.0),
        ]
        summary = CostCalculator.total_savings_summary(resources)
        assert summary["monthly_savings"] == 45.0
        assert summary["annual_savings"] == 540.0
        assert summary["by_provider"]["azure"] == 30.0
        assert summary["by_provider"]["aws"] == 15.0

    def _mock_resource(self, provider: str, cost: float):
        """Create a mock resource for testing."""
        from types import SimpleNamespace
        return SimpleNamespace(
            provider=SimpleNamespace(value=provider),
            estimated_monthly_cost=cost,
        )


# ── ScanResult Tests ──────────────────────────────────────────────────────────


class TestScanResult:
    """Test the ScanResult dataclass."""

    def test_empty_result(self):
        result = ScanResult(provider=CloudProvider.AZURE, resource_type="snapshot")
        assert result.total_count == 0
        assert result.total_monthly_cost == 0.0
        assert len(result.resources) == 0

    def test_with_resources(self):
        r1 = OrphanedResource(
            provider=CloudProvider.AZURE,
            resource_type="snapshot",
            resource_id="id1",
            name="snap1",
            region="eastus",
            subscription_or_account="sub1",
            subscription_name="Test",
            estimated_monthly_cost=10.0,
        )
        result = ScanResult(
            provider=CloudProvider.AZURE,
            resource_type="snapshot",
            resources=[r1],
        )
        assert result.total_count == 1
        assert result.total_monthly_cost == 10.0


# ── DeleteResult Tests ────────────────────────────────────────────────────────


class TestDeleteResult:
    """Test the DeleteResult dataclass."""

    def test_dry_run(self):
        result = DeleteResult(resource_id="id1", resource_name="snap1", success=True, dry_run=True)
        assert result.dry_run is True
        assert result.success is True

    def test_failure(self):
        result = DeleteResult(
            resource_id="id1", resource_name="snap1",
            success=False, dry_run=False, error_message="Permission denied"
        )
        assert result.success is False
        assert result.error_message == "Permission denied"
