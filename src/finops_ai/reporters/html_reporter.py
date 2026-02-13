"""
HTML Reporter — generate beautiful, standalone HTML reports.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("finops-ai.reporters.html")


class HTMLReporter:
    """Generates standalone HTML reports with charts and tables."""

    def __init__(self, output_dir: str = "./reports") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        scan_results: list,
        filename: Optional[str] = None,
        title: str = "FinOps AI — Cloud Cost Report",
    ) -> str:
        """Generate an HTML report file."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = filename or f"finops_report_{timestamp}.html"
        filepath = self.output_dir / filename

        # Aggregate data
        all_resources = []
        total_cost = 0.0
        by_provider: Dict[str, float] = {}
        by_type: Dict[str, int] = {}

        for result in scan_results:
            for r in result.resources:
                all_resources.append(r)
                total_cost += r.estimated_monthly_cost
                prov = r.provider.value if hasattr(r.provider, "value") else str(r.provider)
                by_provider[prov] = by_provider.get(prov, 0) + r.estimated_monthly_cost
                by_type[r.resource_type] = by_type.get(r.resource_type, 0) + 1

        # Sort by cost descending
        all_resources.sort(key=lambda r: r.estimated_monthly_cost, reverse=True)

        html = self._build_html(title, all_resources, total_cost, by_provider, by_type)

        with open(filepath, "w") as f:
            f.write(html)

        logger.info(f"HTML report saved to {filepath}")
        return str(filepath)

    def _build_html(
        self,
        title: str,
        resources: list,
        total_cost: float,
        by_provider: Dict[str, float],
        by_type: Dict[str, int],
    ) -> str:
        """Build the complete HTML string."""
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        rows = ""
        for r in resources:
            provider = r.provider.value if hasattr(r.provider, "value") else str(r.provider)
            status = r.status.value if hasattr(r.status, "value") else str(r.status)
            severity = r.severity.value if hasattr(r.severity, "value") else str(r.severity)
            severity_class = severity.lower()

            rows += f"""
            <tr>
                <td><span class="provider-badge {provider}">{provider.upper()}</span></td>
                <td>{r.resource_type}</td>
                <td title="{r.resource_id}">{r.name}</td>
                <td>{r.region}</td>
                <td><span class="status-badge {status}">{status}</span></td>
                <td>{r.size_gb:.1f}</td>
                <td class="cost">${r.estimated_monthly_cost:.2f}</td>
                <td>{r.age_days}</td>
                <td><span class="severity-badge {severity_class}">{severity}</span></td>
            </tr>"""

        provider_cards = ""
        for prov, cost in sorted(by_provider.items()):
            provider_cards += f"""
            <div class="stat-card">
                <div class="stat-label">{prov.upper()}</div>
                <div class="stat-value">${cost:,.2f}/mo</div>
            </div>"""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        :root {{
            --bg-primary: #0f172a;
            --bg-secondary: #1e293b;
            --bg-card: #1e293b;
            --text-primary: #f1f5f9;
            --text-secondary: #94a3b8;
            --accent-blue: #3b82f6;
            --accent-green: #10b981;
            --accent-red: #ef4444;
            --accent-yellow: #f59e0b;
            --accent-purple: #8b5cf6;
            --border: #334155;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.6;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 2rem; }}
        header {{
            background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%);
            padding: 2rem;
            border-bottom: 1px solid var(--border);
            margin-bottom: 2rem;
        }}
        h1 {{
            font-size: 2rem;
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .meta {{ color: var(--text-secondary); font-size: 0.875rem; margin-top: 0.5rem; }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}
        .stat-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 1.5rem;
            text-align: center;
        }}
        .stat-label {{ color: var(--text-secondary); font-size: 0.875rem; text-transform: uppercase; }}
        .stat-value {{ font-size: 1.75rem; font-weight: 700; margin-top: 0.5rem; }}
        .stat-card:first-child .stat-value {{ color: var(--accent-green); }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: var(--bg-card);
            border-radius: 12px;
            overflow: hidden;
        }}
        th {{
            background: var(--bg-secondary);
            padding: 0.75rem 1rem;
            text-align: left;
            font-size: 0.8rem;
            text-transform: uppercase;
            color: var(--text-secondary);
            border-bottom: 2px solid var(--border);
        }}
        td {{ padding: 0.75rem 1rem; border-bottom: 1px solid var(--border); font-size: 0.9rem; }}
        tr:hover {{ background: rgba(59, 130, 246, 0.05); }}
        .cost {{ color: var(--accent-green); font-weight: 600; }}
        .provider-badge {{
            padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600;
        }}
        .provider-badge.azure {{ background: rgba(0,120,212,0.2); color: #60a5fa; }}
        .provider-badge.aws {{ background: rgba(255,153,0,0.2); color: #f59e0b; }}
        .provider-badge.gcp {{ background: rgba(234,67,53,0.2); color: #f87171; }}
        .status-badge {{
            padding: 2px 8px; border-radius: 4px; font-size: 0.75rem;
        }}
        .status-badge.orphaned {{ background: rgba(239,68,68,0.2); color: #f87171; }}
        .status-badge.unattached {{ background: rgba(245,158,11,0.2); color: #fbbf24; }}
        .status-badge.zombie {{ background: rgba(139,92,246,0.2); color: #a78bfa; }}
        .status-badge.idle {{ background: rgba(59,130,246,0.2); color: #60a5fa; }}
        .status-badge.empty {{ background: rgba(107,114,128,0.2); color: #9ca3af; }}
        .severity-badge {{ padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; }}
        .severity-badge.critical {{ background: rgba(239,68,68,0.3); color: #f87171; }}
        .severity-badge.high {{ background: rgba(245,158,11,0.2); color: #fbbf24; }}
        .severity-badge.medium {{ background: rgba(59,130,246,0.2); color: #60a5fa; }}
        .severity-badge.low {{ background: rgba(107,114,128,0.2); color: #9ca3af; }}
        footer {{ text-align: center; padding: 2rem; color: var(--text-secondary); font-size: 0.8rem; }}
    </style>
</head>
<body>
    <header>
        <div class="container">
            <h1>🔍 {title}</h1>
            <p class="meta">Generated: {now} | FinOps AI v1.0.0</p>
        </div>
    </header>
    <div class="container">
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Total Monthly Waste</div>
                <div class="stat-value">${total_cost:,.2f}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Annual Savings Potential</div>
                <div class="stat-value" style="color:var(--accent-blue)">${total_cost * 12:,.2f}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Resources Found</div>
                <div class="stat-value" style="color:var(--accent-yellow)">{len(resources)}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Resource Types</div>
                <div class="stat-value" style="color:var(--accent-purple)">{len(by_type)}</div>
            </div>
            {provider_cards}
        </div>

        <table>
            <thead>
                <tr>
                    <th>Provider</th><th>Type</th><th>Name</th><th>Region</th>
                    <th>Status</th><th>Size (GB)</th><th>Monthly Cost</th>
                    <th>Age (Days)</th><th>Severity</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
    </div>
    <footer>
        <p>Generated by FinOps AI — Multi-Cloud Cost Optimization Platform</p>
    </footer>
</body>
</html>"""
