"""Tests for alert job helpers: stop-loss detection and per-day dedup."""

from datetime import date

import pandas as pd

from src.config import AlertConfig, AppConfig
from src.scheduler.jobs import _stop_loss_alerts
from src.storage.queries import QueryService


def _hold_position_with_quote(queries: QueryService, close: float) -> None:
    queries.upsert_portfolio_holding("a_share", "600519", "贵州茅台", 100, 1450.0)
    queries.upsert_quotes(
        "a_share",
        "600519",
        pd.DataFrame(
            [
                {
                    "date": date(2026, 10, 21),
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1000.0,
                    "turnover": 1_000_000.0,
                    "change_pct": -2.0,
                }
            ]
        ),
    )


def test_stop_loss_flags_holdings_below_threshold(test_db):
    """A holding down 20% against a -15% stop-loss line raises an alert."""
    queries = QueryService(test_db)
    _hold_position_with_quote(queries, close=1160.0)
    config = AppConfig(alerts=AlertConfig(stop_loss_threshold=-15.0))

    alerts = _stop_loss_alerts(config, queries)

    assert len(alerts) == 1
    assert alerts[0]["symbol"] == "600519"
    assert alerts[0]["alert_type"] == "止损警告"
    assert "-15.0%" in alerts[0]["message"]


def test_stop_loss_ignores_holdings_above_threshold(test_db):
    """A holding down only 5% stays silent against a -15% stop-loss line."""
    queries = QueryService(test_db)
    _hold_position_with_quote(queries, close=1377.5)
    config = AppConfig(alerts=AlertConfig(stop_loss_threshold=-15.0))

    assert _stop_loss_alerts(config, queries) == []


def test_save_alert_if_new_deduplicates_per_symbol_type_and_day(test_db):
    """The second identical alert on a day is dropped; a new day fires again."""
    queries = QueryService(test_db)

    assert queries.save_alert_if_new("600519", "止损警告", date(2026, 10, 21), "msg") is True
    assert queries.save_alert_if_new("600519", "止损警告", date(2026, 10, 21), "msg") is False
    assert queries.save_alert_if_new("600519", "成交量异常放大", date(2026, 10, 21), "msg") is True
    assert queries.save_alert_if_new("600519", "止损警告", date(2026, 10, 22), "msg") is True
