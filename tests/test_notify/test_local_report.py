"""Tests for email credential preflight and the on-disk report fallback."""

import json

from src.config import EmailConfig
from src.notify.local_report import save_report


def _usable_config(**overrides) -> EmailConfig:
    base = {
        "sender": "me@qq.com",
        "password": "abcdefghijklmnop",
        "recipients": ["me@qq.com"],
    }
    return EmailConfig(**{**base, **overrides})


def test_usable_config_reports_no_problem():
    assert _usable_config().credential_problem() is None
    assert _usable_config().is_usable() is True


def test_unresolved_placeholder_is_detected():
    """An unset ${VAR} must be caught before it reaches SMTP AUTH."""
    config = _usable_config(password="${EMAIL_SMTP_PASSWORD}")
    problem = config.credential_problem()
    assert problem is not None
    assert "EMAIL_SMTP_PASSWORD" in problem
    assert config.is_usable() is False


def test_empty_password_is_detected():
    assert "password" in _usable_config(password="").credential_problem()


def test_missing_sender_and_recipients_are_detected():
    assert "sender" in _usable_config(sender="").credential_problem()
    assert "recipients" in _usable_config(recipients=[]).credential_problem()


def test_save_report_writes_json_and_html(tmp_path):
    """A report that cannot be emailed must survive on disk."""
    report = {"date": "2026-08-08", "type": "daily_brief", "individual": {"600519": {}}}
    path = save_report(report, "<html>brief</html>", reports_dir=tmp_path)

    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["type"] == "daily_brief"
    html_files = list(tmp_path.glob("*.html"))
    assert len(html_files) == 1
    assert html_files[0].read_text(encoding="utf-8") == "<html>brief</html>"


def test_save_report_without_html_writes_json_only(tmp_path):
    path = save_report({"date": "2026-08-08", "type": "daily_brief"}, reports_dir=tmp_path)
    assert path.exists()
    assert list(tmp_path.glob("*.html")) == []


def test_save_report_creates_missing_directory(tmp_path):
    target = tmp_path / "nested" / "reports"
    path = save_report({"date": "2026-08-08", "type": "alert"}, reports_dir=target)
    assert path.parent == target


def test_save_report_keeps_non_serializable_values(tmp_path):
    """default=str keeps dates and Decimals from breaking the fallback."""
    from datetime import date

    path = save_report(
        {"date": date(2026, 8, 8), "type": "daily_brief", "when": date(2026, 8, 8)},
        reports_dir=tmp_path,
    )
    assert json.loads(path.read_text(encoding="utf-8"))["when"] == "2026-08-08"
