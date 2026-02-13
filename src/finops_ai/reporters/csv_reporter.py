"""
CSV Reporter — export scan results to CSV for spreadsheet analysis.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("finops-ai.reporters.csv")


class CSVReporter:
    """Generates CSV reports from scan results."""

    HEADERS = [
        "Provider", "Resource Type", "Resource ID", "Name", "Region",
        "Account", "Resource Group", "Status", "Size (GB)",
        "Monthly Cost ($)", "Age (Days)", "Created", "Severity", "Tags",
    ]

    def __init__(self, output_dir: str = "./reports") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        scan_results: list,
        filename: Optional[str] = None,
    ) -> str:
        """Generate a CSV report file."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = filename or f"finops_report_{timestamp}.csv"
        filepath = self.output_dir / filename

        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(self.HEADERS)

            for result in scan_results:
                for r in result.resources:
                    provider = r.provider.value if hasattr(r.provider, "value") else str(r.provider)
                    status = r.status.value if hasattr(r.status, "value") else str(r.status)
                    severity = r.severity.value if hasattr(r.severity, "value") else str(r.severity)
                    tags_str = "; ".join(f"{k}={v}" for k, v in r.tags.items())

                    writer.writerow([
                        provider, r.resource_type, r.resource_id, r.name, r.region,
                        r.subscription_or_account, r.resource_group, status, r.size_gb,
                        r.estimated_monthly_cost, r.age_days, r.created_time, severity,
                        tags_str,
                    ])

        logger.info(f"CSV report saved to {filepath}")
        return str(filepath)
