"""
GCP Scope Resolver — correctly resolves project lists from various GCP scoping primitives.

The previous implementation assumed a single ``project_id`` could contain
sub-projects, which is structurally incorrect in GCP. This module provides
the proper resolution logic for:

- **project**: Direct single-project access.
- **folder**: Uses the Resource Manager API to list child projects under a folder.
- **billing_account**: Uses the Cloud Billing API to list projects linked to
  a billing account.

Each resolution path optionally supports ``resource_labels`` filtering
to isolate specific workloads within a project.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("finops-ai.gcp.scope")


class GCPScopeType(str, Enum):
    """Valid GCP scoping primitives."""

    PROJECT = "project"
    FOLDER = "folder"
    BILLING_ACCOUNT = "billing_account"


class GCPScopeResolver:
    """
    Resolves a list of GCP project IDs from a given scope.

    This class encapsulates the GCP-specific logic for determining which
    projects to scan based on the user's provided scope type and ID.

    Args:
        credentials: GCP credentials object (``google.auth.credentials.Credentials``).
            If ``None``, Application Default Credentials (ADC) are used.

    Example::

        resolver = GCPScopeResolver(credentials)

        # Direct project access
        projects = resolver.resolve_projects("project", "my-project-123")
        # -> ["my-project-123"]

        # Folder-level discovery
        projects = resolver.resolve_projects("folder", "123456789")
        # -> ["child-project-a", "child-project-b", ...]

        # Billing-account-level discovery
        projects = resolver.resolve_projects(
            "billing_account", "01ABCD-234EFG-567HIJ"
        )
        # -> ["billing-linked-project-1", ...]
    """

    def __init__(self, credentials: Any = None) -> None:
        self._credentials = credentials

    def resolve_projects(
        self,
        scope_type: str,
        scope_id: str,
        resource_labels: Optional[Dict[str, str]] = None,
    ) -> List[str]:
        """
        Resolve a list of project IDs from the given scope.

        Args:
            scope_type: One of ``'project'``, ``'folder'``, or ``'billing_account'``.
            scope_id: The GCP project ID, folder ID, or billing account ID.
            resource_labels: Optional label filters. When provided with
                ``scope_type='folder'``, only projects whose labels match
                all entries in this dict are included.

        Returns:
            List of resolved GCP project IDs.

        Raises:
            ValueError: If ``scope_type`` is not a recognised value.
            ImportError: If required GCP SDK packages are not installed.
        """
        # Normalise and validate scope type
        try:
            resolved_type = GCPScopeType(scope_type.lower())
        except ValueError:
            valid = [t.value for t in GCPScopeType]
            raise ValueError(
                f"Invalid scope_type '{scope_type}'. Must be one of: {valid}"
            )

        if resolved_type == GCPScopeType.PROJECT:
            return self._resolve_project(scope_id)
        elif resolved_type == GCPScopeType.FOLDER:
            return self._resolve_folder(scope_id, resource_labels)
        elif resolved_type == GCPScopeType.BILLING_ACCOUNT:
            return self._resolve_billing_account(scope_id, resource_labels)

        # Unreachable, but satisfies type‐checker
        raise ValueError(f"Unhandled scope_type: {resolved_type}")  # pragma: no cover

    # ── Private Resolution Strategies ──────────────────────────────────

    @staticmethod
    def _resolve_project(project_id: str) -> List[str]:
        """
        Direct project access — simply returns the project ID in a list.

        No API call is needed; the project ID is assumed to be valid.
        """
        logger.info("Scope: direct project '%s'", project_id)
        return [project_id]

    def _resolve_folder(
        self,
        folder_id: str,
        resource_labels: Optional[Dict[str, str]] = None,
    ) -> List[str]:
        """
        List child projects under a GCP folder via Resource Manager v3.

        Uses ``resourcemanager_v3.ProjectsClient.list_projects`` with
        ``parent=folders/{folder_id}`` to discover all projects directly
        within the folder.

        Args:
            folder_id: Numeric GCP folder ID.
            resource_labels: Optional label filter applied to project labels.

        Returns:
            List of active project IDs found under the folder.
        """
        try:
            from google.cloud import resourcemanager_v3
        except ImportError:
            raise ImportError(
                "google-cloud-resource-manager is required for folder scoping. "
                "Install with: pip install google-cloud-resource-manager>=1.10.0"
            )

        client = resourcemanager_v3.ProjectsClient(credentials=self._credentials)

        parent = f"folders/{folder_id}"
        logger.info("Resolving projects under folder '%s'", parent)

        request = resourcemanager_v3.ListProjectsRequest(parent=parent)
        projects: List[str] = []

        for project in client.list_projects(request=request):
            # Only include ACTIVE projects
            if project.state.name != "ACTIVE":
                logger.debug(
                    "Skipping non-active project '%s' (state=%s)",
                    project.project_id,
                    project.state.name,
                )
                continue

            # Apply label filter if provided
            if resource_labels and not self._labels_match(
                dict(project.labels), resource_labels
            ):
                logger.debug(
                    "Skipping project '%s': labels don't match filter",
                    project.project_id,
                )
                continue

            projects.append(project.project_id)

        logger.info("Resolved %d projects under folder '%s'", len(projects), parent)
        return projects

    def _resolve_billing_account(
        self,
        billing_account_id: str,
        resource_labels: Optional[Dict[str, str]] = None,
    ) -> List[str]:
        """
        List projects linked to a GCP billing account.

        Uses ``billing_v1.CloudBillingClient.list_project_billing_info``
        with ``name=billingAccounts/{billing_account_id}`` to discover
        all projects associated with the billing account.

        Args:
            billing_account_id: GCP billing account ID
                (e.g., ``'01ABCD-234EFG-567HIJ'``).
            resource_labels: Optional label filter. When provided, only
                projects whose labels (fetched via Resource Manager)
                match all entries are included.

        Returns:
            List of project IDs linked to the billing account.
        """
        try:
            from google.cloud import billing_v1
        except ImportError:
            raise ImportError(
                "google-cloud-billing is required for billing account scoping. "
                "Install with: pip install google-cloud-billing>=1.11.0"
            )

        client = billing_v1.CloudBillingClient(credentials=self._credentials)

        billing_name = f"billingAccounts/{billing_account_id}"
        logger.info("Resolving projects linked to billing account '%s'", billing_name)

        request = billing_v1.ListProjectBillingInfoRequest(name=billing_name)
        projects: List[str] = []

        for info in client.list_project_billing_info(request=request):
            if not info.billing_enabled:
                logger.debug(
                    "Skipping project '%s': billing not enabled",
                    info.project_id,
                )
                continue

            projects.append(info.project_id)

        # Apply label filtering if requested (requires Resource Manager lookup)
        if resource_labels and projects:
            projects = self._filter_by_labels(projects, resource_labels)

        logger.info(
            "Resolved %d projects for billing account '%s'",
            len(projects),
            billing_name,
        )
        return projects

    # ── Label Filtering Helpers ────────────────────────────────────────

    def _filter_by_labels(
        self,
        project_ids: List[str],
        resource_labels: Dict[str, str],
    ) -> List[str]:
        """
        Filter a list of project IDs by matching their project-level labels.

        Fetches each project's metadata from the Resource Manager API
        and checks whether all entries in ``resource_labels`` are present
        in the project's labels.
        """
        try:
            from google.cloud import resourcemanager_v3
        except ImportError:
            logger.warning(
                "google-cloud-resource-manager not installed; "
                "cannot filter by labels, returning all projects"
            )
            return project_ids

        client = resourcemanager_v3.ProjectsClient(credentials=self._credentials)
        filtered: List[str] = []

        for pid in project_ids:
            try:
                project = client.get_project(name=f"projects/{pid}")
                if self._labels_match(dict(project.labels), resource_labels):
                    filtered.append(pid)
                else:
                    logger.debug(
                        "Project '%s' excluded by label filter", pid
                    )
            except Exception as exc:
                logger.warning(
                    "Could not fetch labels for project '%s': %s", pid, exc
                )
                # Include the project to avoid silent data loss
                filtered.append(pid)

        return filtered

    @staticmethod
    def _labels_match(
        project_labels: Dict[str, str],
        required_labels: Dict[str, str],
    ) -> bool:
        """
        Check whether all required labels are present and match in the project.

        Returns ``True`` if every key-value pair in ``required_labels``
        exists in ``project_labels``.
        """
        return all(
            project_labels.get(k) == v for k, v in required_labels.items()
        )
