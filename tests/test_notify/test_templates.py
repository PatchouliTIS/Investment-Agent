"""Tests for report email template rendering."""

import pytest

from src.config import EmailConfig
from src.notify.email_sender import EmailSender


@pytest.mark.parametrize("template_name", ["daily_brief.html", "weekly_deep.html"])
def test_templates_render_a_zero_cost_holding(template_name):
    """Gifted or transferred holdings have no cost-basis percentage but still render."""
    report = {
        "date": "2026-03-02",
        "individual": {},
        "valuation": {
            "holdings": [
                {
                    "name": "测试基金",
                    "symbol": "510300",
                    "shares": 100.0,
                    "cost_price": 0.0,
                    "currency": "CNY",
                    "latest_price": 1.2,
                    "market_value": 120.0,
                    "unrealized_pnl": 120.0,
                    "unrealized_pnl_pct": None,
                }
            ],
            "by_currency": [
                {
                    "currency": "CNY",
                    "market_value": 120.0,
                    "unrealized_pnl": 120.0,
                    "unrealized_pnl_pct": None,
                }
            ],
        },
        "portfolio": {},
    }

    html = EmailSender(EmailConfig()).jinja_env.get_template(template_name).render(report=report)

    assert "测试基金" in html
    assert "120.00" in html