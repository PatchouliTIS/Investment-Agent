"""Tests for database models and queries."""

from datetime import date

import pandas as pd

from src.storage.queries import QueryService


def test_create_tables(test_db):
    """Test that all tables are created."""
    from src.storage.models import Base

    table_names = list(Base.metadata.tables.keys())
    assert "stock_quotes" in table_names
    assert "fund_nav" in table_names
    assert "fund_flow" in table_names
    assert "financial_reports" in table_names
    assert "news" in table_names
    assert "analysis_reports" in table_names
    assert "alert_events" in table_names
    assert "portfolio" in table_names


def test_upsert_and_query_quotes(test_db):
    """Test quote upsert and retrieval."""
    qs = QueryService(test_db)

    df = pd.DataFrame(
        [
            {
                "date": date(2026, 3, 1),
                "open": 100.0,
                "high": 105.0,
                "low": 99.0,
                "close": 103.0,
                "volume": 10000,
                "turnover": 1030000,
                "change_pct": 3.0,
            },
            {
                "date": date(2026, 3, 2),
                "open": 103.0,
                "high": 107.0,
                "low": 102.0,
                "close": 106.0,
                "volume": 12000,
                "turnover": 1272000,
                "change_pct": 2.91,
            },
        ]
    )
    qs.upsert_quotes("a_share", "600519", df)

    result = qs.get_quotes("a_share", "600519", date(2026, 3, 1), date(2026, 3, 2))
    assert len(result) == 2
    assert result.iloc[0]["close"] == 103.0


def test_upsert_idempotent(test_db):
    """Test that upserting the same data twice doesn't create duplicates."""
    qs = QueryService(test_db)

    df = pd.DataFrame(
        [{"date": date(2026, 3, 1), "open": 100, "high": 105, "low": 99, "close": 103, "volume": 10000, "turnover": 1030000, "change_pct": 3.0}]
    )
    qs.upsert_quotes("a_share", "600519", df)
    qs.upsert_quotes("a_share", "600519", df)

    result = qs.get_quotes("a_share", "600519", date(2026, 3, 1), date(2026, 3, 1))
    assert len(result) == 1


def test_save_alert_if_new_is_idempotent(test_db):
    """The same daily alert should only be sent and stored once."""
    qs = QueryService(test_db)

    saved = qs.save_alert_if_new(
        "600519", "价格异动 - 大涨", date(2026, 3, 2), "涨跌幅超过阈值"
    )
    duplicate = qs.save_alert_if_new(
        "600519", "价格异动 - 大涨", date(2026, 3, 2), "涨跌幅超过阈值"
    )

    assert saved is True
    assert duplicate is False
