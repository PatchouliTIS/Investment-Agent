"""Tests for normalized market-data synchronization."""

from datetime import date

import pandas as pd

from src.data.akshare_client import AkshareDataClient
from src.data.sync import DataSyncService
from src.storage.queries import QueryService


def test_normalize_quotes_maps_akshare_columns():
    """AKShare's Chinese quote columns map to the storage contract."""
    raw = pd.DataFrame(
        [
            {
                "日期": "2026-03-02",
                "开盘": "100.0",
                "最高": "105.0",
                "最低": "99.0",
                "收盘": "103.0",
                "成交量": "10,000",
                "成交额": "1,030,000",
                "涨跌幅": "3.0%",
            }
        ]
    )

    result = AkshareDataClient._normalize_quotes(raw)

    assert result.to_dict("records") == [
        {
            "date": date(2026, 3, 2),
            "open": 100.0,
            "high": 105.0,
            "low": 99.0,
            "close": 103.0,
            "volume": 10000,
            "turnover": 1030000,
            "change_pct": 3.0,
        }
    ]


class FakeDataClient:
    """Network-free AKShare replacement with deterministic one-row responses."""

    def __init__(self):
        self.calls = []

    @staticmethod
    def _quotes():
        return pd.DataFrame(
            [
                {
                    "date": date(2026, 3, 2),
                    "open": 100.0,
                    "high": 105.0,
                    "low": 99.0,
                    "close": 103.0,
                    "volume": 10000.0,
                    "turnover": 1030000.0,
                    "change_pct": 3.0,
                }
            ]
        )

    def fetch_a_share_quotes(self, symbol, start, end):
        self.calls.append(("a_share", symbol))
        return self._quotes()

    def fetch_hk_quotes(self, symbol, start, end):
        self.calls.append(("hk", symbol))
        return self._quotes()

    def fetch_us_quotes(self, symbol, start, end):
        self.calls.append(("us", symbol))
        return self._quotes()

    def fetch_fund_nav(self, fund_code, start, end):
        self.calls.append(("fund", fund_code))
        return pd.DataFrame(
            [
                {
                    "date": date(2026, 3, 2),
                    "nav": 1.2,
                    "acc_nav": 1.5,
                    "daily_return": 1.0,
                }
            ]
        )

    def fetch_latest_financial_indicators(self, symbol):
        return date(2025, 12, 31), {"净资产收益率": 12.5}

    def fetch_fund_flow(self, symbol):
        return pd.DataFrame(
            [
                {
                    "date": date(2026, 3, 2),
                    "main_net_inflow": 100.0,
                    "small_net_inflow": -20.0,
                    "total_net_inflow": 80.0,
                }
            ]
        )

    def fetch_news(self, symbol):
        return pd.DataFrame(
            [
                {
                    "title": "测试新闻",
                    "content": "测试内容",
                    "url": "https://example.test/news",
                    "published_at": "2026-03-02 10:00:00",
                }
            ]
        )


def test_sync_all_persists_each_watchlist_market(sample_config, test_db):
    """Synchronization stores quotes, funds, and A-share enrichment independently."""
    client = FakeDataClient()
    service = DataSyncService(sample_config, test_db, client=client)

    summary = service.sync_all()
    queries = QueryService(test_db)

    assert summary == {"a_share_quotes": 1, "fund_nav": 1, "hk_quotes": 1, "us_quotes": 1}
    assert len(queries.get_quotes("a_share", "600519", date(2026, 3, 2), date(2026, 3, 2))) == 1
    assert len(queries.get_quotes("hk", "00700", date(2026, 3, 2), date(2026, 3, 2))) == 1
    assert len(queries.get_quotes("us", "AAPL", date(2026, 3, 2), date(2026, 3, 2))) == 1
    assert client.calls == [
        ("a_share", "600519"),
        ("fund", "510300"),
        ("hk", "00700"),
        ("us", "AAPL"),
    ]