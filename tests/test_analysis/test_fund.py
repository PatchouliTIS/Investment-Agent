"""Tests for fund NAV analysis."""

from datetime import timedelta

import pandas as pd

from src.analysis.fund import FundAnalyst
from src.storage.queries import QueryService
from src.utils.chinese_calendar import shanghai_today


class FakeLLM:
    """Minimal deterministic LLM for analysis tests."""

    def chat_json(self, system_prompt, user_message, request_context="unspecified"):
        return {"summary": "净值走势稳健", "rating": "bullish", "confidence": 0.8}


def test_fund_analyst_calculates_nav_risk_return_metrics(test_db):
    """Fund analysis exposes deterministic metrics alongside the LLM conclusion."""
    today = shanghai_today()
    nav = pd.DataFrame(
        [
            {
                "date": today - timedelta(days=3 - index),
                "nav": value,
                "acc_nav": value,
                "daily_return": 0.0,
            }
            for index, value in enumerate([1.0, 1.1, 1.0, 1.2])
        ]
    )
    QueryService(test_db).upsert_fund_nav("510300", "etf", nav)

    result = FundAnalyst(FakeLLM(), test_db).analyze("510300")

    assert result.rating == "bullish"
    assert result.details["latest_nav"] == 1.2
    assert result.details["1d_return_pct"] == 20.0
    assert result.details["period_return_pct"] == 20.0
    assert result.details["max_drawdown_pct"] == -9.09
    assert result.details["key_metrics"]["区间最大回撤"] == "-9.09%"