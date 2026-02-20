"""Centralized logging configuration for the CEO application."""

from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

LOG_DIR = Path("./logs")

_APP_LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
_APP_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_TOOL_LOGGER_NAME = "ceo.tool_results"


def setup_logging(log_dir: Path | None = None) -> None:
    """Configure logging for the entire application.

    Call once at startup before CeoApp is created.
    """
    base_dir = log_dir or LOG_DIR
    base_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Daily rotating file handler — all application logs
    app_handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(base_dir / "ceo.log"),
        when="midnight",
        interval=1,
        backupCount=14,
        encoding="utf-8",
    )
    app_handler.setLevel(logging.DEBUG)
    app_handler.setFormatter(
        logging.Formatter(_APP_LOG_FORMAT, datefmt=_APP_LOG_DATE_FORMAT)
    )
    root.addHandler(app_handler)

    # Dedicated tool-result logger — JSON Lines, size-rotated
    tool_logger = logging.getLogger(_TOOL_LOGGER_NAME)
    tool_logger.propagate = False
    tool_handler = logging.handlers.RotatingFileHandler(
        filename=str(base_dir / "tool_results.jsonl"),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    tool_handler.setLevel(logging.DEBUG)
    tool_handler.setFormatter(logging.Formatter("%(message)s"))
    tool_logger.addHandler(tool_handler)


def log_tool_result(
    result: Dict[str, Any],
    co_id: str | None = None,
    step_number: int | None = None,
) -> None:
    """Log a full tool result as a JSON Lines entry."""
    tool_logger = logging.getLogger(_TOOL_LOGGER_NAME)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "co_id": co_id,
        "step": step_number,
        "tool": result.get("tool", "unknown"),
        "status": result.get("status", "unknown"),
        "output": result.get("output") or result.get("content") or None,
        "error": result.get("error") or None,
        "reason": result.get("reason") or None,
    }
    try:
        tool_logger.info(json.dumps(entry, ensure_ascii=False, default=str))
    except Exception:
        tool_logger.info(
            json.dumps({"tool": result.get("tool"), "error": "serialization_failed"})
        )
