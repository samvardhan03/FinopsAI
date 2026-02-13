"""
JSON Reporter — export scan results to structured JSON.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("finops-ai.reporters.json")


class JSONReporter:
    """Generates structured JSON reports from scan results."""

    def __init__(self, output_dir: str = "./reports") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _resource_to_dict(self, resource: Any) -> Dict[str, Any]:
        """Convert an OrphanedResource to a serializable dict."""
        return {
            "provider": resource.provider.value if hasattr(resource.provider, "value") else str(resource.provider),
            "resource_type": resource.resource_type,
            "resource_id": resource.resource_id,
            "name": resource.name,
            "region": resource.region,
            "account": resource.subscription_or_account,
            "account_name": resource.subscription_name,
            "resource_group": resource.resource_group,
            "status": resource.status.value if hasattr(resource.status, "value") else str(resource.status),
            "size_gb": resource.size_gb,
            "estimated_monthly_cost": resource.estimated_monthly_cost,
            "age_days": resource.age_days,
            "created_time": resource.created_time,
            "last_used_time": resource.last_used_time,
            "tags": resource.tags,
            "severity": resource.severity.value if hasattr(resource.severity, "value") else str(resource.severity),
        }

    def generate(
        self,
        scan_results: list,
        filename: Optional[str] = None,
    ) -> str:
        """
        Generate a JSON report file.

        Args:
            scan_results: List of ScanResult objects.
            filename: Optional custom filename.

        Returns:
            Path to the generated report file.
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = filename or f"finops_report_{timestamp}.json"
        filepath = self.output_dir / filename

        all_resources = []
        total_cost = 0.0
        by_provider: Dict[str, float] = {}

        for result in scan_results:
            for resource in result.resources:
                all_resources.append(self._resource_to_dict(resource))
                total_cost += resource.estimated_monthly_cost
                prov = resource.provider.value if hasattr(resource.provider, "value") else str(resource.provider)
                by_provider[prov] = by_provider.get(prov, 0) + resource.estimated_monthly_cost

        report = {
            "metadata": {
                "generated_at": datetime.utcnow().isoformat(),
                "tool": "finops-ai",
                "version": "1.0.0",
            },
            "summary": {
                "total_resources": len(all_resources),
                "total_monthly_cost": round(total_cost, 2),
                "total_annual_cost": round(total_cost * 12, 2),
                "by_provider": {k: round(v, 2) for k, v in by_provider.items()},
            },
            "resources": all_resources,
        }

        with open(filepath, "w") as f:
            json.dump(report, f, indent=2, default=str)

        logger.info(f"JSON report saved to {filepath}")
        return str(filepath)
