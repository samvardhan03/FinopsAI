"""
Policy engine — governance as code for cloud resources.

Loads YAML policy definitions and evaluates them against scan results
to determine what actions (alert, delete, stop, tag) should be taken.
"""

from __future__ import annotations

import fnmatch
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

from finops_ai.core.base_manager import OrphanedResource

logger = logging.getLogger("finops-ai.policy")


@dataclass
class Policy:
    """A single governance policy."""

    name: str
    resource_type: str                       # e.g. "azure_snapshot", "all"
    condition: str                           # e.g. "orphaned == true AND age_days > 30"
    action: str                              # e.g. "delete", "alert", "tag", "stop"
    schedule: Optional[str] = None           # Cron expression
    approval_required: bool = False
    notification: Optional[str] = None       # Webhook URL
    description: str = ""
    severity: str = "medium"
    enabled: bool = True


@dataclass
class PolicyMatch:
    """A resource matched by a policy."""

    policy: Policy
    resource: OrphanedResource
    action: str
    approval_required: bool


@dataclass
class PolicyEvalResult:
    """Result of evaluating all policies against resources."""

    matches: List[PolicyMatch] = field(default_factory=list)
    total_policies: int = 0
    total_resources: int = 0

    @property
    def actions_by_type(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for m in self.matches:
            counts[m.action] = counts.get(m.action, 0) + 1
        return counts

    @property
    def requires_approval(self) -> List[PolicyMatch]:
        return [m for m in self.matches if m.approval_required]

    @property
    def auto_executable(self) -> List[PolicyMatch]:
        return [m for m in self.matches if not m.approval_required]


class ConditionEvaluator:
    """
    Evaluates policy condition strings against resource attributes.

    Supports a simple expression language:
      "orphaned == true AND age_days > 30"
      "tags.owner == null"
      "estimated_monthly_cost > 50"
      "resource_type == snapshot"
    """

    @staticmethod
    def evaluate(condition: str, resource: OrphanedResource) -> bool:
        """
        Evaluate a condition string against a resource.

        Args:
            condition: The condition expression.
            resource: The resource to evaluate against.

        Returns:
            True if the condition matches.
        """
        # Split on AND/OR
        parts = re.split(r'\s+AND\s+', condition, flags=re.IGNORECASE)

        for part in parts:
            part = part.strip()
            if not ConditionEvaluator._evaluate_single(part, resource):
                return False

        return True

    @staticmethod
    def _evaluate_single(expr: str, resource: OrphanedResource) -> bool:
        """Evaluate a single comparison expression."""
        # Parse operator
        for op in [">=", "<=", "!=", "==", ">", "<"]:
            if op in expr:
                left, right = expr.split(op, 1)
                left = left.strip()
                right = right.strip()
                left_val = ConditionEvaluator._resolve_value(left, resource)
                right_val = ConditionEvaluator._parse_literal(right)
                return ConditionEvaluator._compare(left_val, op, right_val)

        return False

    @staticmethod
    def _resolve_value(field_path: str, resource: OrphanedResource) -> Any:
        """Resolve a dotted field path against a resource."""
        # Handle special status mappings
        if field_path == "orphaned":
            return resource.status.value == "orphaned"
        if field_path == "idle":
            return resource.status.value == "idle"
        if field_path == "zombie":
            return resource.status.value == "zombie"

        # Handle dotted paths (e.g., "tags.owner")
        parts = field_path.split(".")
        obj: Any = resource

        for part in parts:
            if isinstance(obj, dict):
                obj = obj.get(part)
            elif hasattr(obj, part):
                obj = getattr(obj, part)
            else:
                return None

        return obj

    @staticmethod
    def _parse_literal(value: str) -> Any:
        """Parse a literal value from condition string."""
        # Null check
        if value.lower() == "null" or value.lower() == "none":
            return None

        # Boolean
        if value.lower() == "true":
            return True
        if value.lower() == "false":
            return False

        # Numeric
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            pass

        # String (strip quotes if present)
        return value.strip("'\"")

    @staticmethod
    def _compare(left: Any, op: str, right: Any) -> bool:
        """Compare two values with the given operator."""
        try:
            if op == "==":
                return left == right
            elif op == "!=":
                return left != right
            elif op == ">":
                return float(left) > float(right)
            elif op == "<":
                return float(left) < float(right)
            elif op == ">=":
                return float(left) >= float(right)
            elif op == "<=":
                return float(left) <= float(right)
        except (TypeError, ValueError):
            return False
        return False


class PolicyEngine:
    """
    Governance policy engine.

    Loads YAML policy definitions, evaluates them against scan results,
    and determines what actions should be taken.
    """

    def __init__(self) -> None:
        self.policies: List[Policy] = []
        self._evaluator = ConditionEvaluator()

    def load(self, path: str) -> int:
        """
        Load policies from a YAML file or directory.

        Args:
            path: Path to YAML file or directory containing YAML files.

        Returns:
            Number of policies loaded.
        """
        p = Path(path)
        count = 0

        if p.is_file():
            count += self._load_file(p)
        elif p.is_dir():
            for yaml_file in sorted(p.glob("**/*.yaml")):
                count += self._load_file(yaml_file)
            for yml_file in sorted(p.glob("**/*.yml")):
                count += self._load_file(yml_file)
        else:
            logger.warning(f"Policy path not found: {path}")

        logger.info(f"Loaded {count} policies from {path}")
        return count

    def _load_file(self, path: Path) -> int:
        """Load policies from a single YAML file."""
        try:
            with open(path) as f:
                data = yaml.safe_load(f)

            if not data or "policies" not in data:
                logger.warning(f"No 'policies' key in {path}")
                return 0

            count = 0
            for policy_data in data["policies"]:
                policy = Policy(
                    name=policy_data.get("name", "unnamed"),
                    resource_type=policy_data.get("resource_type", "all"),
                    condition=policy_data.get("condition", ""),
                    action=policy_data.get("action", "alert"),
                    schedule=policy_data.get("schedule"),
                    approval_required=policy_data.get("approval_required", False),
                    notification=policy_data.get("notification"),
                    description=policy_data.get("description", ""),
                    severity=policy_data.get("severity", "medium"),
                    enabled=policy_data.get("enabled", True),
                )
                if policy.enabled:
                    self.policies.append(policy)
                    count += 1

            return count

        except Exception as e:
            logger.error(f"Failed to load policy file {path}: {e}")
            return 0

    def evaluate(self, resources: List[OrphanedResource]) -> PolicyEvalResult:
        """
        Evaluate all policies against a list of resources.

        Args:
            resources: List of resources to evaluate.

        Returns:
            PolicyEvalResult with all matches.
        """
        result = PolicyEvalResult(
            total_policies=len(self.policies),
            total_resources=len(resources),
        )

        for policy in self.policies:
            for resource in resources:
                # Check resource type match
                if not self._resource_type_matches(policy.resource_type, resource):
                    continue

                # Evaluate condition
                if policy.condition and self._evaluator.evaluate(policy.condition, resource):
                    match = PolicyMatch(
                        policy=policy,
                        resource=resource,
                        action=policy.action,
                        approval_required=policy.approval_required,
                    )
                    result.matches.append(match)
                    logger.debug(
                        f"Policy '{policy.name}' matched resource '{resource.name}' "
                        f"→ action: {policy.action}"
                    )

        logger.info(
            f"Policy evaluation: {len(result.matches)} matches from "
            f"{result.total_policies} policies against {result.total_resources} resources"
        )
        return result

    def _resource_type_matches(self, policy_type: str, resource: OrphanedResource) -> bool:
        """Check if a policy's resource_type filter matches a resource."""
        if policy_type == "all":
            return True

        # Support "azure_snapshot", "aws_ebs_volume", etc.
        full_type = f"{resource.provider.value}_{resource.resource_type}"
        return fnmatch.fnmatch(full_type, policy_type) or fnmatch.fnmatch(
            resource.resource_type, policy_type
        )

    def clear(self) -> None:
        """Remove all loaded policies."""
        self.policies.clear()
