"""
Slack Reporter — send scan results to Slack via webhook.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("finops-ai.reporters.slack")


class SlackReporter:
    """Sends FinOps scan summaries to Slack via Incoming Webhook."""

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def send(
        self,
        scan_results: list,
        channel: Optional[str] = None,
        title: str = "☁️ FinOps AI — Cost Report",
    ) -> bool:
        """
        Send a scan summary to Slack.

        Args:
            scan_results: List of ScanResult objects.
            channel: Optional Slack channel override.
            title: Message title.

        Returns:
            True if message was sent successfully.
        """
        import requests

        total_resources = sum(len(r.resources) for r in scan_results)
        total_cost = sum(r.estimated_monthly_cost for r in scan_results if hasattr(r, 'estimated_monthly_cost'))

        # Fallback cost calculation
        if total_cost == 0:
            for result in scan_results:
                total_cost += sum(r.estimated_monthly_cost for r in result.resources)

        # Build provider breakdown
        by_provider: Dict[str, Dict[str, Any]] = {}
        for result in scan_results:
            for r in result.resources:
                prov = r.provider.value if hasattr(r.provider, "value") else str(r.provider)
                if prov not in by_provider:
                    by_provider[prov] = {"count": 0, "cost": 0.0}
                by_provider[prov]["count"] += 1
                by_provider[prov]["cost"] += r.estimated_monthly_cost

        # Build Slack blocks
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": title},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Resources Found:*\n{total_resources}"},
                    {"type": "mrkdwn", "text": f"*Monthly Savings:*\n${total_cost:,.2f}"},
                    {"type": "mrkdwn", "text": f"*Annual Savings:*\n${total_cost * 12:,.2f}"},
                    {"type": "mrkdwn", "text": f"*Providers:*\n{', '.join(by_provider.keys())}"},
                ],
            },
            {"type": "divider"},
        ]

        # Provider breakdowns
        for prov, data in by_provider.items():
            emoji = {"azure": "🔵", "aws": "🟠", "gcp": "🔴"}.get(prov, "☁️")
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"{emoji} *{prov.upper()}*: "
                        f"{data['count']} resources | ${data['cost']:,.2f}/mo"
                    ),
                },
            })

        # Top 5 most expensive
        all_resources = []
        for result in scan_results:
            all_resources.extend(result.resources)
        all_resources.sort(key=lambda r: r.estimated_monthly_cost, reverse=True)

        if all_resources:
            top_text = "*Top 5 Most Expensive:*\n"
            for r in all_resources[:5]:
                top_text += f"• `{r.name}` — ${r.estimated_monthly_cost:.2f}/mo ({r.resource_type})\n"
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": top_text}})

        payload = {"blocks": blocks}
        if channel:
            payload["channel"] = channel

        try:
            resp = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            resp.raise_for_status()
            logger.info("Slack notification sent successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")
            return False
