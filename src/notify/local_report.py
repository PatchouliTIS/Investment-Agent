"""Filesystem fallback for reports that cannot be emailed.

When SMTP credentials are missing or delivery fails, the analysis has already
cost tokens. Writing it to disk keeps the run useful and lets a later retry read
it back instead of regenerating.
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from src.utils.chinese_calendar import shanghai_now

REPORTS_DIR = Path("data/reports")


def save_report(report: dict, html: str | None = None, reports_dir: Path | None = None) -> Path:
    """Write a report as JSON (plus optional HTML) and return the JSON path."""
    target_dir = reports_dir or REPORTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    report_type = report.get("type", "report")
    stamp = shanghai_now().strftime("%Y%m%d-%H%M%S")
    base = f"{report.get('date', 'unknown')}-{report_type}-{stamp}"

    json_path = target_dir / f"{base}.json"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    if html is not None:
        html_path = target_dir / f"{base}.html"
        html_path.write_text(html, encoding="utf-8")
        logger.info(f"Report saved locally json={json_path} html={html_path}")
    else:
        logger.info(f"Report saved locally json={json_path}")

    return json_path
