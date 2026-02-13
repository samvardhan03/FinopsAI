"""
Configuration management for FinOps AI.

Supports loading from YAML config files, environment variables, and CLI args.
Uses Pydantic Settings for validation and type coercion.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# ── Provider Auth Configs ──────────────────────────────────────────────────────


class AzureAuthConfig(BaseModel):
    """Azure authentication configuration."""

    method: str = Field(default="cli", description="Auth method: cli, managed-identity, service-principal")
    subscription_id: Optional[str] = Field(default=None, description="Specific subscription ID")
    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    managed_identity_client_id: Optional[str] = None


class AWSAuthConfig(BaseModel):
    """AWS authentication configuration."""

    profile: Optional[str] = Field(default=None, description="AWS CLI profile name")
    region: str = Field(default="us-east-1", description="Default AWS region")
    regions: List[str] = Field(default_factory=lambda: ["us-east-1"], description="Regions to scan")
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None


class GCPAuthConfig(BaseModel):
    """GCP authentication configuration."""

    project_id: Optional[str] = Field(default=None, description="GCP project ID")
    credentials_file: Optional[str] = Field(default=None, description="Path to service account JSON")
    zones: List[str] = Field(default_factory=lambda: ["us-central1-a"], description="Zones to scan")


# ── Provider Config ────────────────────────────────────────────────────────────


class ProvidersConfig(BaseModel):
    """Configuration for all cloud providers."""

    azure: AzureAuthConfig = Field(default_factory=AzureAuthConfig)
    aws: AWSAuthConfig = Field(default_factory=AWSAuthConfig)
    gcp: GCPAuthConfig = Field(default_factory=GCPAuthConfig)
    enabled: List[str] = Field(
        default_factory=lambda: ["azure"],
        description="Enabled providers: azure, aws, gcp",
    )


# ── Policy Config ──────────────────────────────────────────────────────────────


class PolicyConfig(BaseModel):
    """Governance policy configuration."""

    enabled: bool = Field(default=False, description="Enable policy engine")
    policy_dirs: List[str] = Field(
        default_factory=list,
        description="Directories containing policy YAML files",
    )


# ── Reporting Config ───────────────────────────────────────────────────────────


class ReportingConfig(BaseModel):
    """Reporting and notification configuration."""

    output_dir: str = Field(default="./reports", description="Directory for report output")
    formats: List[str] = Field(
        default_factory=lambda: ["json"],
        description="Report formats: json, csv, html",
    )
    slack_webhook_url: Optional[str] = None
    teams_webhook_url: Optional[str] = None


# ── ML Config ──────────────────────────────────────────────────────────────────


class MLConfig(BaseModel):
    """Machine learning engine configuration."""

    enabled: bool = Field(default=False, description="Enable ML recommendations")
    anomaly_sensitivity: float = Field(
        default=0.05, ge=0.001, le=1.0, description="Anomaly detection sensitivity (lower = more sensitive)"
    )
    forecast_months: int = Field(default=6, ge=1, le=24, description="Forecast horizon in months")
    rightsizing_cpu_threshold: float = Field(
        default=0.3, ge=0.0, le=1.0, description="CPU utilization threshold for right-sizing"
    )
    rightsizing_memory_threshold: float = Field(
        default=0.3, ge=0.0, le=1.0, description="Memory utilization threshold for right-sizing"
    )


# ── Scan Config ────────────────────────────────────────────────────────────────


class ScanConfig(BaseModel):
    """Resource scan configuration."""

    zombie_vm_days: int = Field(default=30, ge=1, description="Days a VM must be stopped to be 'zombie'")
    snapshot_orphan_days: int = Field(default=0, ge=0, description="Min age in days for orphaned snapshots")
    resource_types: List[str] = Field(
        default_factory=lambda: ["all"],
        description="Resource types to scan: all, snapshots, disks, ips, vms, etc.",
    )
    exclude_tags: Dict[str, str] = Field(
        default_factory=dict,
        description="Skip resources with these tags (e.g., {'env': 'production'})",
    )
    exclude_resource_groups: List[str] = Field(
        default_factory=list,
        description="Resource groups to exclude from scanning",
    )


# ── Root Config ────────────────────────────────────────────────────────────────


DEFAULT_CONFIG_DIR = Path.home() / ".finops-ai"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.yaml"


class FinOpsConfig(BaseSettings):
    """Root configuration for FinOps AI."""

    model_config = SettingsConfigDict(
        env_prefix="FINOPS_",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    scan: ScanConfig = Field(default_factory=ScanConfig)
    policies: PolicyConfig = Field(default_factory=PolicyConfig)
    reporting: ReportingConfig = Field(default_factory=ReportingConfig)
    ml: MLConfig = Field(default_factory=MLConfig)
    log_level: str = Field(default="INFO", description="Log level: DEBUG, INFO, WARNING, ERROR")
    dry_run: bool = Field(default=True, description="Global dry-run toggle")

    @classmethod
    def load(cls, config_path: Optional[str] = None, **overrides: Any) -> "FinOpsConfig":
        """
        Load configuration from YAML file, env vars, and overrides.

        Priority (highest to lowest):
        1. Explicit overrides (CLI args)
        2. Environment variables (FINOPS_*)
        3. YAML config file
        4. Defaults
        """
        yaml_data: Dict[str, Any] = {}

        # Determine config path
        path = Path(config_path) if config_path else DEFAULT_CONFIG_FILE

        if path.exists():
            with open(path) as f:
                yaml_data = yaml.safe_load(f) or {}

        # Merge: YAML data serves as base, overrides take priority
        merged = {**yaml_data, **overrides}
        return cls(**merged)

    def save(self, config_path: Optional[str] = None) -> Path:
        """Save current configuration to YAML file."""
        path = Path(config_path) if config_path else DEFAULT_CONFIG_FILE
        path.parent.mkdir(parents=True, exist_ok=True)

        data = self.model_dump(exclude_none=True)
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        return path


def get_default_config() -> FinOpsConfig:
    """Get configuration with defaults, loading from file if available."""
    return FinOpsConfig.load()
