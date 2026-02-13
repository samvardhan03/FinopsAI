"""
FinOps AI — CLI Interface.

Beautiful command-line interface built with Click + Rich for
multi-cloud cost optimization.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from finops_ai.__version__ import __version__

console = Console()


# ── ASCII Banner ───────────────────────────────────────────────────────────────

BANNER = """
[bold cyan]
  ███████╗██╗███╗   ██╗ ██████╗ ██████╗ ███████╗     █████╗ ██╗
  ██╔════╝██║████╗  ██║██╔═══██╗██╔══██╗██╔════╝    ██╔══██╗██║
  █████╗  ██║██╔██╗ ██║██║   ██║██████╔╝███████╗    ███████║██║
  ██╔══╝  ██║██║╚██╗██║██║   ██║██╔═══╝ ╚════██║    ██╔══██║██║
  ██║     ██║██║ ╚████║╚██████╔╝██║     ███████║    ██║  ██║██║
  ╚═╝     ╚═╝╚═╝  ╚═══╝ ╚═════╝ ╚═╝     ╚══════╝    ╚═╝  ╚═╝╚═╝
[/bold cyan]
[dim]  Multi-Cloud Cost Optimization Platform  •  v{version}[/dim]
"""


def show_banner() -> None:
    """Display the FinOps AI banner."""
    console.print(BANNER.format(version=__version__))


# ── Main CLI Group ─────────────────────────────────────────────────────────────


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="finops-ai")
@click.option("--config", "-c", type=click.Path(exists=True), help="Path to YAML config file")
@click.option("--dry-run/--no-dry-run", default=True, help="Dry-run mode (default: enabled)")
@click.option("--log-level", type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]), default="INFO")
@click.option("--log-file", type=click.Path(), default=None, help="Log file path")
@click.pass_context
def cli(ctx: click.Context, config: Optional[str], dry_run: bool, log_level: str, log_file: Optional[str]) -> None:
    """FinOps AI — Multi-Cloud Cost Optimization Platform.

    Detect orphaned resources, estimate savings, and clean up cloud waste
    across Azure, AWS, and GCP.
    """
    ctx.ensure_object(dict)

    # Setup logging
    from finops_ai.utils.logger import setup_logging
    setup_logging(level=log_level, log_file=log_file)

    # Load config
    from finops_ai.config import FinOpsConfig
    if config:
        ctx.obj["config"] = FinOpsConfig.from_yaml(config, overrides={"dry_run": dry_run})
    else:
        ctx.obj["config"] = FinOpsConfig(dry_run=dry_run, log_level=log_level)

    ctx.obj["dry_run"] = dry_run

    if ctx.invoked_subcommand is None:
        show_banner()
        console.print("[dim]Run [bold]finops-ai --help[/bold] to see available commands.[/dim]\n")


# ── Scan Command ───────────────────────────────────────────────────────────────


@cli.command()
@click.option("--provider", "-p", type=click.Choice(["azure", "aws", "gcp", "all"]), default="all",
              help="Cloud provider to scan")
@click.option("--resource-type", "-t", multiple=True,
              help="Specific resource types to scan (e.g., snapshot, disk, vm)")
@click.option("--subscription", "-s", help="Azure subscription ID")
@click.option("--region", "-r", multiple=True, help="AWS/GCP regions to scan")
@click.option("--project", help="GCP project ID")
@click.option("--output", "-o", type=click.Choice(["table", "json", "csv"]), default="table",
              help="Output format")
@click.option("--report", type=click.Path(), help="Save report to file")
@click.pass_context
def scan(ctx: click.Context, provider: str, resource_type: tuple, subscription: Optional[str],
         region: tuple, project: Optional[str], output: str, report: Optional[str]) -> None:
    """Scan cloud resources for waste and optimization opportunities."""
    show_banner()
    config = ctx.obj["config"]
    dry_run = ctx.obj["dry_run"]

    console.print(Panel(
        f"[bold]Scanning {provider.upper()} resources[/bold]\n"
        f"[dim]Dry-run: {'✅ Yes' if dry_run else '❌ No'}  |  "
        f"Types: {', '.join(resource_type) if resource_type else 'All'}[/dim]",
        title="🔍 FinOps AI Scan",
        border_style="cyan",
    ))

    from finops_ai.core.auth_manager import AuthManager
    scan_results = []

    # ── Azure scan ─────────────────────────────────────────────────
    if provider in ("azure", "all"):
        try:
            console.print("\n[provider.azure]█ Azure[/provider.azure] — Scanning...", style="bold")
            credential = AuthManager.get_azure_credential(config.providers.azure.auth)

            from finops_ai.providers.azure.snapshot_manager import AzureSnapshotManager
            from finops_ai.providers.azure.disk_manager import AzureDiskManager
            from finops_ai.providers.azure.network_manager import AzureNetworkManager
            from finops_ai.providers.azure.vm_manager import AzureVMManager
            from finops_ai.providers.azure.app_service_manager import AzureAppServiceManager
            from finops_ai.providers.azure.resource_group_manager import AzureResourceGroupManager

            managers = [
                ("Snapshots", AzureSnapshotManager),
                ("Disks", AzureDiskManager),
                ("Network", AzureNetworkManager),
                ("VMs", AzureVMManager),
                ("App Service", AzureAppServiceManager),
                ("Resource Groups", AzureResourceGroupManager),
            ]

            sub_id = subscription or config.providers.azure.subscription_id

            for name, mgr_class in managers:
                if resource_type and name.lower().replace(" ", "_") not in resource_type:
                    continue
                try:
                    with console.status(f"  Scanning {name}..."):
                        manager = mgr_class(credential, sub_id)
                        result = manager.scan()
                        scan_results.append(result)
                        console.print(f"  ✅ {name}: [bold]{len(result.resources)}[/bold] found "
                                       f"([cost]${result.total_estimated_cost:.2f}/mo[/cost])")
                except ImportError:
                    console.print(f"  ⚠️  {name}: Azure SDK not installed", style="warning")
                except Exception as e:
                    console.print(f"  ❌ {name}: {e}", style="error")

        except ImportError:
            console.print("  ⚠️  Azure SDK not installed. Run: pip install finops-ai[azure]", style="warning")
        except Exception as e:
            console.print(f"  ❌ Azure error: {e}", style="error")

    # ── AWS scan ───────────────────────────────────────────────────
    if provider in ("aws", "all"):
        try:
            console.print("\n[provider.aws]█ AWS[/provider.aws] — Scanning...", style="bold")
            session = AuthManager.get_aws_session(config.providers.aws.auth)

            from finops_ai.providers.aws.ec2_manager import AWSEC2Manager
            from finops_ai.providers.aws.ebs_manager import AWSEBSManager
            from finops_ai.providers.aws.network_manager import AWSNetworkManager
            from finops_ai.providers.aws.rds_manager import AWSRDSManager

            regions_list = list(region) if region else (config.providers.aws.regions or ["us-east-1"])

            managers = [
                ("EC2", AWSEC2Manager),
                ("EBS", AWSEBSManager),
                ("Network", AWSNetworkManager),
                ("RDS", AWSRDSManager),
            ]

            for name, mgr_class in managers:
                try:
                    with console.status(f"  Scanning {name}..."):
                        manager = mgr_class(session, regions_list)
                        result = manager.scan()
                        scan_results.append(result)
                        console.print(f"  ✅ {name}: [bold]{len(result.resources)}[/bold] found "
                                       f"([cost]${result.total_estimated_cost:.2f}/mo[/cost])")
                except ImportError:
                    console.print(f"  ⚠️  {name}: AWS SDK not installed", style="warning")
                except Exception as e:
                    console.print(f"  ❌ {name}: {e}", style="error")

        except ImportError:
            console.print("  ⚠️  AWS SDK not installed. Run: pip install finops-ai[aws]", style="warning")
        except Exception as e:
            console.print(f"  ❌ AWS error: {e}", style="error")

    # ── GCP scan ───────────────────────────────────────────────────
    if provider in ("gcp", "all"):
        try:
            console.print("\n[provider.gcp]█ GCP[/provider.gcp] — Scanning...", style="bold")
            project_id = project or config.providers.gcp.project_id

            if not project_id:
                console.print("  ⚠️  No GCP project ID configured", style="warning")
            else:
                credentials = AuthManager.get_gcp_credentials(config.providers.gcp.auth)

                from finops_ai.providers.gcp.compute_manager import GCPComputeManager
                from finops_ai.providers.gcp.network_manager import GCPNetworkManager
                from finops_ai.providers.gcp.storage_manager import GCPStorageManager

                managers = [
                    ("Compute", GCPComputeManager),
                    ("Network", GCPNetworkManager),
                    ("Storage", GCPStorageManager),
                ]

                for name, mgr_class in managers:
                    try:
                        with console.status(f"  Scanning {name}..."):
                            manager = mgr_class(project_id, credentials)
                            result = manager.scan()
                            scan_results.append(result)
                            console.print(f"  ✅ {name}: [bold]{len(result.resources)}[/bold] found "
                                           f"([cost]${result.total_estimated_cost:.2f}/mo[/cost])")
                    except ImportError:
                        console.print(f"  ⚠️  {name}: GCP SDK not installed", style="warning")
                    except Exception as e:
                        console.print(f"  ❌ {name}: {e}", style="error")

        except ImportError:
            console.print("  ⚠️  GCP SDK not installed. Run: pip install finops-ai[gcp]", style="warning")
        except Exception as e:
            console.print(f"  ❌ GCP error: {e}", style="error")

    # ── Display results ────────────────────────────────────────────
    _display_scan_summary(scan_results)

    if output == "json" or report:
        from finops_ai.reporters.json_reporter import JSONReporter
        reporter = JSONReporter()
        path = reporter.generate(scan_results, filename=report)
        console.print(f"\n📄 Report saved: [link]{path}[/link]")
    elif output == "csv":
        from finops_ai.reporters.csv_reporter import CSVReporter
        reporter = CSVReporter()
        path = reporter.generate(scan_results, filename=report)
        console.print(f"\n📄 CSV report saved: [link]{path}[/link]")


def _display_scan_summary(scan_results: list) -> None:
    """Display a beautiful summary table."""
    all_resources = []
    for result in scan_results:
        all_resources.extend(result.resources)

    if not all_resources:
        console.print("\n✨ [bold green]No wasteful resources found! Your cloud is clean.[/bold green]")
        return

    total_cost = sum(r.estimated_monthly_cost for r in all_resources)

    console.print(f"\n{'─' * 72}")
    console.print(Panel(
        f"[bold green]Total Resources Found: {len(all_resources)}[/bold green]\n"
        f"[bold cost]Monthly Savings: ${total_cost:,.2f}[/bold cost]\n"
        f"[bold]Annual Savings: ${total_cost * 12:,.2f}[/bold]",
        title="📊 Scan Summary",
        border_style="green",
    ))

    # Top 15 resources by cost
    all_resources.sort(key=lambda r: r.estimated_monthly_cost, reverse=True)

    table = Table(
        title="Top Wasteful Resources",
        box=box.ROUNDED,
        show_lines=False,
        header_style="bold cyan",
        title_style="bold white",
    )
    table.add_column("Provider", style="bold", width=8)
    table.add_column("Type", width=16)
    table.add_column("Name", width=30)
    table.add_column("Region", width=14)
    table.add_column("Status", width=12)
    table.add_column("Size", justify="right", width=8)
    table.add_column("Cost/mo", justify="right", style="green", width=10)
    table.add_column("Age", justify="right", width=6)

    for r in all_resources[:15]:
        provider = r.provider.value if hasattr(r.provider, "value") else str(r.provider)
        status = r.status.value if hasattr(r.status, "value") else str(r.status)

        provider_style = {
            "azure": "blue", "aws": "yellow", "gcp": "red",
        }.get(provider, "white")

        status_style = {
            "orphaned": "red", "unattached": "yellow", "zombie": "magenta",
            "idle": "cyan", "empty": "dim",
        }.get(status, "white")

        table.add_row(
            Text(provider.upper(), style=provider_style),
            r.resource_type,
            r.name[:28],
            r.region[:12],
            Text(status, style=status_style),
            f"{r.size_gb:.0f} GB" if r.size_gb else "—",
            f"${r.estimated_monthly_cost:.2f}",
            f"{r.age_days}d" if r.age_days else "—",
        )

    console.print(table)


# ── Report Command ─────────────────────────────────────────────────────────────


@cli.command()
@click.option("--format", "-f", "fmt", type=click.Choice(["html", "json", "csv"]), default="html",
              help="Report format")
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.pass_context
def report(ctx: click.Context, fmt: str, output: Optional[str]) -> None:
    """Generate a standalone report from scan results."""
    console.print(f"Generating {fmt.upper()} report...", style="bold")
    console.print("[dim]Run 'finops-ai scan' first, then pass results to generate reports.[/dim]")


# ── Version Command ────────────────────────────────────────────────────────────


@cli.command()
def version() -> None:
    """Display version and system information."""
    show_banner()

    table = Table(box=box.SIMPLE, show_header=False)
    table.add_column("Key", style="bold cyan")
    table.add_column("Value")

    table.add_row("Version", __version__)
    table.add_row("Python", sys.version.split()[0])
    table.add_row("Platform", sys.platform)

    # Check installed providers
    providers = []
    try:
        import azure.identity  # noqa
        providers.append("Azure ✅")
    except ImportError:
        providers.append("Azure ❌")

    try:
        import boto3  # noqa
        providers.append("AWS ✅")
    except ImportError:
        providers.append("AWS ❌")

    try:
        import google.cloud.compute_v1  # noqa
        providers.append("GCP ✅")
    except ImportError:
        providers.append("GCP ❌")

    table.add_row("Providers", " | ".join(providers))

    try:
        import sklearn  # noqa
        table.add_row("ML Engine", "✅ Available")
    except ImportError:
        table.add_row("ML Engine", "❌ Not installed")

    console.print(table)


# ── Init Command ───────────────────────────────────────────────────────────────


@cli.command()
@click.option("--output", "-o", default="finops-ai.yaml", help="Config file output path")
def init(output: str) -> None:
    """Generate a sample configuration file."""
    sample_config = """# FinOps AI Configuration
# See docs for full reference: https://finops-ai.readthedocs.io

dry_run: true
log_level: INFO

providers:
  azure:
    enabled: true
    auth:
      method: cli  # cli, managed_identity, service_principal
    subscription_id: ""  # Leave empty to scan all

  aws:
    enabled: false
    auth:
      method: profile  # profile, keys, sso
      profile_name: default
    regions:
      - us-east-1
      - us-west-2

  gcp:
    enabled: false
    auth:
      method: adc  # adc, service_account
    project_id: ""

scan:
  resource_types:
    - snapshot
    - disk
    - vm
    - public_ip
    - load_balancer
  max_age_days: 0  # 0 = no filter
  min_cost: 0.0

policies:
  policies_dir: ./policies
  enforce: false

reporting:
  formats:
    - table
  output_dir: ./reports

ml:
  enabled: false
  anomaly_detection: false
  cost_forecasting: false
"""
    with open(output, "w") as f:
        f.write(sample_config)

    console.print(f"✅ Configuration file created: [bold]{output}[/bold]")
    console.print("[dim]Edit the file and run 'finops-ai scan' to get started.[/dim]")


def main() -> None:
    """Entry point for the CLI."""
    cli(obj={})


if __name__ == "__main__":
    main()
