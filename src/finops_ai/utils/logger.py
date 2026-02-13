"""
Rich-based structured logging for FinOps AI.

Provides both beautiful console output (via Rich) and JSON file logging
for audit trails and machine-readable analysis.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

# Custom theme for FinOps AI console output
FINOPS_THEME = Theme(
    {
        "info": "cyan",
        "warning": "yellow",
        "error": "bold red",
        "critical": "bold white on red",
        "success": "bold green",
        "cost": "bold magenta",
        "provider.azure": "bold blue",
        "provider.aws": "bold yellow",
        "provider.gcp": "bold red",
        "severity.critical": "bold white on red",
        "severity.high": "bold red",
        "severity.medium": "bold yellow",
        "severity.low": "cyan",
        "severity.info": "dim",
    }
)

console = Console(theme=FINOPS_THEME)


class JSONFileHandler(logging.Handler):
    """Logging handler that writes structured JSON lines to a file."""

    def __init__(self, filepath: str) -> None:
        super().__init__()
        self.filepath = Path(filepath)
        self.filepath.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            log_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "module": record.module,
                "function": record.funcName,
                "line": record.lineno,
            }
            # Include extra fields if present
            if hasattr(record, "resource_id"):
                log_entry["resource_id"] = record.resource_id
            if hasattr(record, "provider"):
                log_entry["provider"] = record.provider
            if hasattr(record, "action"):
                log_entry["action"] = record.action

            with open(self.filepath, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            self.handleError(record)


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    json_log: bool = False,
) -> logging.Logger:
    """
    Configure logging for FinOps AI.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR).
        log_file: Optional path for JSON audit log file.
        json_log: If True and log_file is set, write JSON-structured logs.

    Returns:
        Configured root logger for finops-ai.
    """
    root_logger = logging.getLogger("finops-ai")
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Rich console handler — beautiful terminal output
    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
        tracebacks_show_locals=True,
    )
    rich_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    root_logger.addHandler(rich_handler)

    # JSON file handler for audit trails
    if log_file:
        if json_log:
            json_handler = JSONFileHandler(log_file)
            json_handler.setLevel(logging.DEBUG)
            root_logger.addHandler(json_handler)
        else:
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(
                logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            )
            root_logger.addHandler(file_handler)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under the finops-ai namespace."""
    return logging.getLogger(f"finops-ai.{name}")
