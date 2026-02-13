"""
Unit tests for the Policy Engine.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from finops_ai.core.base_manager import CloudProvider, OrphanedResource, ResourceStatus, Severity
from finops_ai.core.policy_engine import PolicyEngine, ConditionEvaluator, Policy


# ── ConditionEvaluator Tests ──────────────────────────────────────────────────


class TestConditionEvaluator:
    """Test the ConditionEvaluator."""

    def _make_resource(self, **kwargs):
        defaults = dict(
            provider=CloudProvider.AZURE,
            resource_type="snapshot",
            resource_id="id1",
            name="test-snap",
            region="eastus",
            subscription_or_account="sub1",
            subscription_name="Test",
            age_days=45,
            estimated_monthly_cost=50.0,
            size_gb=100.0,
            tags={"env": "dev"},
        )
        defaults.update(kwargs)
        return OrphanedResource(**defaults)

    def test_equality(self):
        r = self._make_resource()
        assert ConditionEvaluator.evaluate("resource_type == snapshot", r) is True

    def test_inequality(self):
        r = self._make_resource()
        assert ConditionEvaluator.evaluate("resource_type != disk", r) is True

    def test_greater_than(self):
        r = self._make_resource(age_days=45)
        assert ConditionEvaluator.evaluate("age_days > 30", r) is True
        assert ConditionEvaluator.evaluate("age_days > 60", r) is False

    def test_less_than(self):
        r = self._make_resource(estimated_monthly_cost=5.0)
        assert ConditionEvaluator.evaluate("estimated_monthly_cost < 10", r) is True

    def test_greater_equal(self):
        r = self._make_resource(size_gb=100.0)
        assert ConditionEvaluator.evaluate("size_gb >= 100", r) is True

    def test_boolean_true(self):
        r = self._make_resource()
        # orphaned status check
        assert ConditionEvaluator.evaluate("status == orphaned", r) is True

    def test_and_condition(self):
        r = self._make_resource(age_days=45, estimated_monthly_cost=50.0)
        assert ConditionEvaluator.evaluate("age_days > 30 AND estimated_monthly_cost > 10", r) is True
        assert ConditionEvaluator.evaluate("age_days > 60 AND estimated_monthly_cost > 10", r) is False

    def test_dotted_path_tags(self):
        r = self._make_resource(tags={"env": "dev"})
        assert ConditionEvaluator.evaluate("tags.env == dev", r) is True

    def test_dotted_path_missing(self):
        r = self._make_resource(tags={})
        assert ConditionEvaluator.evaluate("tags.env == dev", r) is False


# ── PolicyEngine Tests ────────────────────────────────────────────────────────


class TestPolicyEngine:
    """Test the PolicyEngine."""

    def _make_resource(self, **kwargs):
        defaults = dict(
            provider=CloudProvider.AZURE,
            resource_type="snapshot",
            resource_id="id1",
            name="test-snap",
            region="eastus",
            subscription_or_account="sub1",
            subscription_name="Test",
            age_days=45,
            estimated_monthly_cost=50.0,
        )
        defaults.update(kwargs)
        return OrphanedResource(**defaults)

    def test_load_policy(self):
        policy = Policy(
            name="test-policy",
            description="Test",
            resource_type="snapshot",
            condition="age_days > 30",
            action="delete",
        )
        engine = PolicyEngine()
        engine.policies.append(policy)
        assert len(engine.policies) == 1

    def test_evaluate_match(self):
        policy = Policy(
            name="old-snapshots",
            description="Delete old snapshots",
            resource_type="snapshot",
            condition="age_days > 30",
            action="delete",
        )
        engine = PolicyEngine()
        engine.policies.append(policy)
        r = self._make_resource(age_days=45)
        result = engine.evaluate([r])

        assert result.total_policies == 1
        assert len(result.matches) == 1
        assert result.matches[0].action == "delete"

    def test_evaluate_no_match(self):
        policy = Policy(
            name="old-snapshots",
            description="Delete old snapshots",
            resource_type="snapshot",
            condition="age_days > 90",
            action="delete",
        )
        engine = PolicyEngine()
        engine.policies.append(policy)
        r = self._make_resource(age_days=30)
        result = engine.evaluate([r])

        assert len(result.matches) == 0

    def test_resource_type_mismatch(self):
        policy = Policy(
            name="disk-policy",
            description="Delete disks",
            resource_type="disk",
            condition="age_days > 30",
            action="delete",
        )
        engine = PolicyEngine()
        engine.policies.append(policy)
        r = self._make_resource(resource_type="snapshot")
        result = engine.evaluate([r])

        assert len(result.matches) == 0

    def test_wildcard_resource_type(self):
        policy = Policy(
            name="all-resources",
            description="Match all",
            resource_type="*",
            condition="age_days > 30",
            action="alert",
        )
        engine = PolicyEngine()
        engine.policies.append(policy)
        r = self._make_resource(age_days=45)
        result = engine.evaluate([r])

        assert len(result.matches) == 1

    def test_load_from_yaml_file(self):
        """Test loading policies from a YAML file."""
        yaml_content = """policies:
  - name: test-policy
    description: Delete old snapshots
    resource_type: snapshot
    condition: "age_days > 30"
    action: delete
    severity: high
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            try:
                engine = PolicyEngine()
                count = engine.load(f.name)
                assert count >= 1
                assert engine.policies[0].name == "test-policy"
            finally:
                os.unlink(f.name)
