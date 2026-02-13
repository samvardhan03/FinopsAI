"""
Unified multi-cloud authentication manager.

Provides factory methods to obtain credentials for Azure, AWS, and GCP,
abstracting away the differences between CLI, managed identity, service principal,
SSO, and application default credential flows.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from finops_ai.config import AWSAuthConfig, AzureAuthConfig, GCPAuthConfig

logger = logging.getLogger("finops-ai.auth")


class AuthManager:
    """Unified authentication manager for all cloud providers."""

    # ── Azure ──────────────────────────────────────────────────────────────

    @staticmethod
    def get_azure_credential(config: Optional[AzureAuthConfig] = None) -> Any:
        """
        Get Azure credential based on configured auth method.

        Args:
            config: Azure auth configuration. Uses defaults if None.

        Returns:
            Azure credential object (DefaultAzureCredential, ManagedIdentityCredential, etc.)

        Raises:
            ImportError: If azure-identity is not installed.
            ValueError: If service-principal method is missing required fields.
        """
        try:
            from azure.identity import (
                ClientSecretCredential,
                DefaultAzureCredential,
                ManagedIdentityCredential,
            )
        except ImportError:
            raise ImportError(
                "Azure SDK not installed. Install with: pip install finops-ai[azure]"
            )

        if config is None:
            config = AzureAuthConfig()

        method = config.method.lower()

        if method == "cli":
            logger.info("Using Azure CLI authentication")
            return DefaultAzureCredential(exclude_managed_identity_credential=True)

        elif method == "managed-identity":
            logger.info("Using Azure Managed Identity authentication")
            return ManagedIdentityCredential(client_id=config.managed_identity_client_id)

        elif method == "service-principal":
            if not all([config.client_id, config.client_secret, config.tenant_id]):
                raise ValueError(
                    "Service principal auth requires client_id, client_secret, and tenant_id"
                )
            logger.info("Using Azure Service Principal authentication")
            return ClientSecretCredential(
                config.tenant_id, config.client_id, config.client_secret
            )

        elif method == "default":
            logger.info("Using Azure DefaultAzureCredential (auto-detect)")
            return DefaultAzureCredential()

        else:
            raise ValueError(f"Unsupported Azure auth method: {method}")

    # ── AWS ────────────────────────────────────────────────────────────────

    @staticmethod
    def get_aws_session(config: Optional[AWSAuthConfig] = None) -> Any:
        """
        Get AWS boto3 session.

        Args:
            config: AWS auth configuration. Uses defaults if None.

        Returns:
            boto3.Session object.

        Raises:
            ImportError: If boto3 is not installed.
        """
        try:
            import boto3
        except ImportError:
            raise ImportError(
                "AWS SDK not installed. Install with: pip install finops-ai[aws]"
            )

        if config is None:
            config = AWSAuthConfig()

        session_kwargs: dict[str, Any] = {}

        if config.profile:
            session_kwargs["profile_name"] = config.profile
            logger.info(f"Using AWS profile: {config.profile}")

        if config.region:
            session_kwargs["region_name"] = config.region

        if config.access_key_id and config.secret_access_key:
            session_kwargs["aws_access_key_id"] = config.access_key_id
            session_kwargs["aws_secret_access_key"] = config.secret_access_key
            logger.info("Using AWS access key authentication")
        else:
            logger.info("Using AWS default credential chain")

        return boto3.Session(**session_kwargs)

    # ── GCP ────────────────────────────────────────────────────────────────

    @staticmethod
    def get_gcp_credentials(config: Optional[GCPAuthConfig] = None) -> Any:
        """
        Get GCP credentials via Application Default Credentials or service account.

        Args:
            config: GCP auth configuration. Uses defaults if None.

        Returns:
            google.auth.credentials.Credentials object.

        Raises:
            ImportError: If google-auth is not installed.
        """
        try:
            import google.auth
            from google.oauth2 import service_account
        except ImportError:
            raise ImportError(
                "GCP SDK not installed. Install with: pip install finops-ai[gcp]"
            )

        if config is None:
            config = GCPAuthConfig()

        if config.credentials_file:
            logger.info(f"Using GCP service account from: {config.credentials_file}")
            credentials = service_account.Credentials.from_service_account_file(
                config.credentials_file,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            return credentials

        logger.info("Using GCP Application Default Credentials")
        credentials, project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        return credentials
