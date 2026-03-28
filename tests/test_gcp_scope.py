"""
Tests for GCP Scope Resolution — project/folder/billing_account.

Uses unittest.mock to verify the correct GCP API calls are made
for each scope type, without requiring real GCP credentials.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from finops_ai.providers.gcp.scope_resolver import GCPScopeResolver, GCPScopeType


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def resolver() -> GCPScopeResolver:
    """Resolver instance with mock credentials."""
    mock_creds = MagicMock()
    return GCPScopeResolver(credentials=mock_creds)


# ── Enum Tests ──────────────────────────────────────────────────────────


class TestGCPScopeType:
    """Test the GCPScopeType enum."""

    def test_valid_values(self) -> None:
        assert GCPScopeType.PROJECT.value == "project"
        assert GCPScopeType.FOLDER.value == "folder"
        assert GCPScopeType.BILLING_ACCOUNT.value == "billing_account"

    def test_from_string(self) -> None:
        assert GCPScopeType("project") == GCPScopeType.PROJECT
        assert GCPScopeType("folder") == GCPScopeType.FOLDER
        assert GCPScopeType("billing_account") == GCPScopeType.BILLING_ACCOUNT


# ── Project Scope Tests ─────────────────────────────────────────────────


class TestProjectScope:
    """Tests for scope_type='project'."""

    def test_returns_single_project(self, resolver: GCPScopeResolver) -> None:
        """Direct project scope returns the project ID in a list."""
        result = resolver.resolve_projects("project", "my-project-123")
        assert result == ["my-project-123"]

    def test_no_api_calls(self, resolver: GCPScopeResolver) -> None:
        """Project scope should NOT make any API calls."""
        with patch(
            "finops_ai.providers.gcp.scope_resolver.GCPScopeResolver._resolve_folder"
        ) as mock_folder, patch(
            "finops_ai.providers.gcp.scope_resolver.GCPScopeResolver._resolve_billing_account"
        ) as mock_billing:
            resolver.resolve_projects("project", "my-project")
            mock_folder.assert_not_called()
            mock_billing.assert_not_called()

    def test_case_insensitive(self, resolver: GCPScopeResolver) -> None:
        """Scope type should be case-insensitive."""
        result = resolver.resolve_projects("PROJECT", "my-project")
        assert result == ["my-project"]

    def test_labels_ignored_for_project(self, resolver: GCPScopeResolver) -> None:
        """Labels have no effect on direct project scope."""
        result = resolver.resolve_projects(
            "project", "my-project", resource_labels={"env": "prod"}
        )
        assert result == ["my-project"]


# ── Folder Scope Tests ──────────────────────────────────────────────────


class TestFolderScope:
    """Tests for scope_type='folder'."""

    def test_lists_child_projects(self, resolver: GCPScopeResolver) -> None:
        """Folder scope should call ProjectsClient.list_projects with correct parent."""
        import sys

        # Create mock projects
        mock_project_1 = MagicMock()
        mock_project_1.project_id = "child-project-a"
        mock_project_1.state.name = "ACTIVE"
        mock_project_1.labels = {}

        mock_project_2 = MagicMock()
        mock_project_2.project_id = "child-project-b"
        mock_project_2.state.name = "ACTIVE"
        mock_project_2.labels = {}

        mock_inactive = MagicMock()
        mock_inactive.project_id = "deleted-project"
        mock_inactive.state.name = "DELETE_REQUESTED"
        mock_inactive.labels = {}

        # Create a mock module for google.cloud.resourcemanager_v3
        mock_rm = MagicMock()
        mock_client_instance = MagicMock()
        mock_rm.ProjectsClient.return_value = mock_client_instance
        mock_client_instance.list_projects.return_value = [
            mock_project_1,
            mock_project_2,
            mock_inactive,
        ]

        # Inject mock module into sys.modules
        original = sys.modules.get("google.cloud.resourcemanager_v3")
        sys.modules["google.cloud.resourcemanager_v3"] = mock_rm

        try:
            result = resolver.resolve_projects("folder", "123456789")
        finally:
            if original is None:
                sys.modules.pop("google.cloud.resourcemanager_v3", None)
            else:
                sys.modules["google.cloud.resourcemanager_v3"] = original

        # Should only include ACTIVE projects
        assert result == ["child-project-a", "child-project-b"]
        mock_rm.ProjectsClient.assert_called_once()

    def test_folder_with_label_filter(self, resolver: GCPScopeResolver) -> None:
        """Folder scope with resource_labels should filter projects by labels."""
        import sys

        mock_project_matching = MagicMock()
        mock_project_matching.project_id = "matching-project"
        mock_project_matching.state.name = "ACTIVE"
        mock_project_matching.labels = {"env": "staging", "team": "platform"}

        mock_project_no_match = MagicMock()
        mock_project_no_match.project_id = "non-matching-project"
        mock_project_no_match.state.name = "ACTIVE"
        mock_project_no_match.labels = {"env": "production"}

        mock_rm = MagicMock()
        mock_client_instance = MagicMock()
        mock_rm.ProjectsClient.return_value = mock_client_instance
        mock_client_instance.list_projects.return_value = [
            mock_project_matching,
            mock_project_no_match,
        ]

        original = sys.modules.get("google.cloud.resourcemanager_v3")
        sys.modules["google.cloud.resourcemanager_v3"] = mock_rm

        try:
            result = resolver.resolve_projects(
                "folder", "123456789", resource_labels={"env": "staging"}
            )
        finally:
            if original is None:
                sys.modules.pop("google.cloud.resourcemanager_v3", None)
            else:
                sys.modules["google.cloud.resourcemanager_v3"] = original

        assert result == ["matching-project"]


# ── Billing Account Scope Tests ─────────────────────────────────────────


class TestBillingAccountScope:
    """Tests for scope_type='billing_account'."""

    def test_lists_linked_projects(self, resolver: GCPScopeResolver) -> None:
        """Billing account scope should call CloudBillingClient correctly."""
        import sys

        mock_info_1 = MagicMock()
        mock_info_1.project_id = "billing-project-1"
        mock_info_1.billing_enabled = True

        mock_info_2 = MagicMock()
        mock_info_2.project_id = "billing-project-2"
        mock_info_2.billing_enabled = True

        mock_disabled = MagicMock()
        mock_disabled.project_id = "disabled-billing"
        mock_disabled.billing_enabled = False

        mock_billing = MagicMock()
        mock_billing_client = MagicMock()
        mock_billing.CloudBillingClient.return_value = mock_billing_client
        mock_billing_client.list_project_billing_info.return_value = [
            mock_info_1,
            mock_info_2,
            mock_disabled,
        ]

        original = sys.modules.get("google.cloud.billing_v1")
        sys.modules["google.cloud.billing_v1"] = mock_billing

        try:
            result = resolver.resolve_projects(
                "billing_account", "01ABCD-234EFG-567HIJ"
            )
        finally:
            if original is None:
                sys.modules.pop("google.cloud.billing_v1", None)
            else:
                sys.modules["google.cloud.billing_v1"] = original

        # Should only include billing-enabled projects
        assert result == ["billing-project-1", "billing-project-2"]
        mock_billing.CloudBillingClient.assert_called_once()


# ── Error Handling Tests ────────────────────────────────────────────────


class TestScopeErrors:
    """Tests for error handling in scope resolution."""

    def test_invalid_scope_type(self, resolver: GCPScopeResolver) -> None:
        """Invalid scope type should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid scope_type"):
            resolver.resolve_projects("invalid", "some-id")

    def test_invalid_scope_type_partial(self, resolver: GCPScopeResolver) -> None:
        """Partial scope type should still raise ValueError."""
        with pytest.raises(ValueError, match="Invalid scope_type"):
            resolver.resolve_projects("proj", "some-id")


# ── Labels Match Utility Tests ──────────────────────────────────────────


class TestLabelsMatch:
    """Tests for the _labels_match static method."""

    def test_empty_required_labels(self) -> None:
        """No required labels means everything matches."""
        assert GCPScopeResolver._labels_match({"env": "prod"}, {}) is True

    def test_matching_labels(self) -> None:
        """All required labels present and matching."""
        assert GCPScopeResolver._labels_match(
            {"env": "prod", "team": "infra", "cost-center": "123"},
            {"env": "prod", "team": "infra"},
        ) is True

    def test_missing_label_key(self) -> None:
        """Required label key missing from project labels."""
        assert GCPScopeResolver._labels_match(
            {"env": "prod"},
            {"env": "prod", "team": "infra"},
        ) is False

    def test_mismatched_label_value(self) -> None:
        """Required label value doesn't match."""
        assert GCPScopeResolver._labels_match(
            {"env": "staging"},
            {"env": "prod"},
        ) is False

    def test_empty_project_labels(self) -> None:
        """No project labels means no required labels can match."""
        assert GCPScopeResolver._labels_match(
            {},
            {"env": "prod"},
        ) is False
