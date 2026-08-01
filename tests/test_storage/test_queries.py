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


def test_portfolio_valuation_uses_local_prices_and_keeps_currencies_separate(test_db):
    """Holdings use the appropriate local data source without FX aggregation."""
    qs = QueryService(test_db)
    qs.upsert_portfolio_holding("a_share", "600519", "贵州茅台", 10, 100.0)
    qs.upsert_portfolio_holding("fund", "510300", "沪深300ETF", 100, 1.0)
    qs.upsert_quotes(
        "a_share",
        "600519",
        pd.DataFrame(
            [
                {
                    "date": date(2026, 3, 2),
                    "open": 104.0,
                    "high": 106.0,
                    "low": 103.0,
                    "close": 105.0,
                    "volume": 10000,
                    "turnover": 1050000,
                    "change_pct": 5.0,
                }
            ]
        ),
    )
    qs.upsert_fund_nav(
        "510300",
        "etf",
        pd.DataFrame(
            [{"date": date(2026, 3, 2), "nav": 1.2, "acc_nav": 1.2, "daily_return": 1.0}]
        ),
    )

    valuation = qs.get_portfolio_valuation()
    holdings = {holding["symbol"]: holding for holding in valuation["holdings"]}

    assert valuation["unvalued_count"] == 0
    assert holdings["510300"]["market_value"] == 120.0
    assert holdings["600519"]["market_value"] == 1050.0
    assert valuation["by_currency"] == [
        {
            "currency": "CNY",
            "market_value": 1170.0,
            "cost_value": 1100.0,
            "unrealized_pnl": 70.0,
            "unrealized_pnl_pct": 70 / 1100 * 100,
            "valued_count": 2,
        }
    ]


def test_upsert_portfolio_holding_updates_an_existing_position(test_db):
    """A later manual entry replaces the quantity and cost of the same holding."""
    qs = QueryService(test_db)
    qs.upsert_portfolio_holding("a_share", "600519", "贵州茅台", 10, 100.0)
    qs.upsert_portfolio_holding("a_share", "600519", "贵州茅台", 12, 110.0)

    valuation = qs.get_portfolio_valuation()

    assert len(valuation["holdings"]) == 1
    assert valuation["holdings"][0]["shares"] == 12
    assert valuation["holdings"][0]["cost_price"] == 110.0


def test_delete_portfolio_holding_removes_only_the_requested_position(test_db):
    """Deletion is scoped to the same market and symbol as the requested holding."""
    qs = QueryService(test_db)
    qs.upsert_portfolio_holding("a_share", "600519", "贵州茅台", 10, 100.0)
    qs.upsert_portfolio_holding("fund", "510300", "沪深300ETF", 100, 1.0)

    deleted = qs.delete_portfolio_holding("a_share", "600519")
    missing = qs.delete_portfolio_holding("a_share", "600519")

    assert deleted is True
    assert missing is False
    assert [holding["symbol"] for holding in qs.get_portfolio_valuation()["holdings"]] == ["510300"]
