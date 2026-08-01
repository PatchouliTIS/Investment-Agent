"""Tests for normalized market-data synchronization."""

import os
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


def test_akshare_call_bypasses_and_restores_environment_proxies(monkeypatch):
    """Default AKShare calls ignore a broken shell proxy without mutating it permanently."""
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:7897")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:7897")
    seen_proxies = []

    def fetch():
        seen_proxies.append((os.environ.get("http_proxy"), os.environ.get("https_proxy")))
        return pd.DataFrame()

    client = AkshareDataClient(api=object(), retry_delay_seconds=0)
    client._call("proxy_test", fetch)

    assert seen_proxies == [(None, None)]
    assert os.environ["http_proxy"] == "http://127.0.0.1:7897"
    assert os.environ["https_proxy"] == "http://127.0.0.1:7897"


def test_akshare_call_retries_transient_errors():
    """Transient provider errors are retried up to the configured limit."""
    attempts = 0

    def fetch():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("temporary failure")
        return pd.DataFrame()

    client = AkshareDataClient(api=object(), max_retries=1, retry_delay_seconds=0)
    result = client._call("retry_test", fetch)

    assert result.empty
    assert attempts == 2


def test_a_share_quotes_fall_back_to_sina_and_compute_change_pct():
    """An Eastmoney failure uses Sina data while preserving the quote schema."""
    class FakeApi:
        @staticmethod
        def stock_zh_a_hist(**kwargs):
            raise ConnectionError("Eastmoney unavailable")

        @staticmethod
        def stock_zh_a_daily(**kwargs):
            assert kwargs["symbol"] == "sh600519"
            return pd.DataFrame(
                [
                    {
                        "date": "2026-03-01",
                        "open": 100.0,
                        "high": 101.0,
                        "low": 99.0,
                        "close": 100.0,
                        "volume": 10000,
                        "amount": 1000000,
                    },
                    {
                        "date": "2026-03-02",
                        "open": 102.0,
                        "high": 106.0,
                        "low": 101.0,
                        "close": 105.0,
                        "volume": 11000,
                        "amount": 1155000,
                    },
                ]
            )

        @staticmethod
        def stock_zh_a_hist_tx(**kwargs):
            raise AssertionError("Tencent should not be used when Sina succeeds")

    client = AkshareDataClient(api=FakeApi(), max_retries=0)

    quotes = client.fetch_a_share_quotes("600519", date(2026, 3, 1), date(2026, 3, 2))
    fund_flow = client.fetch_fund_flow("600519")

    assert quotes["turnover"].tolist() == [1000000, 1155000]
    assert pd.isna(quotes["change_pct"].iloc[0])
    assert quotes["change_pct"].iloc[1] == 5.0
    assert fund_flow.empty


def test_etf_nav_falls_back_to_sina_and_filters_to_incremental_dates():
    """ETF/LOF synchronization uses Sina data when Eastmoney is unavailable."""
    class FakeApi:
        @staticmethod
        def fund_etf_hist_em(**kwargs):
            raise ConnectionError("Eastmoney unavailable")

        @staticmethod
        def fund_etf_hist_sina(**kwargs):
            assert kwargs["symbol"] == "sh510300"
            return pd.DataFrame(
                [
                    {
                        "date": "2026-02-27",
                        "open": 1.0,
                        "high": 1.0,
                        "low": 1.0,
                        "close": 1.0,
                        "volume": 100,
                        "amount": 100,
                    },
                    {
                        "date": "2026-03-02",
                        "open": 1.2,
                        "high": 1.2,
                        "low": 1.2,
                        "close": 1.2,
                        "volume": 120,
                        "amount": 144,
                    },
                ]
            )

    client = AkshareDataClient(api=FakeApi(), max_retries=0)

    nav = client.fetch_fund_nav("510300", date(2026, 3, 1), date(2026, 3, 2))

    assert nav["acc_nav"].iloc[0] is None
    assert nav.to_dict("records") == [
        {
            "date": date(2026, 3, 2),
            "nav": 1.2,
            "acc_nav": None,
            "daily_return": 20.0,
        }
    ]


def test_hk_and_us_quotes_fall_back_to_sina_and_filter_incremental_dates():
    """HK and U.S. history use Sina when their Eastmoney endpoint is unavailable."""
    class FakeApi:
        @staticmethod
        def stock_hk_hist(**kwargs):
            raise ConnectionError("Eastmoney unavailable")

        @staticmethod
        def stock_hk_daily(**kwargs):
            assert kwargs == {"symbol": "00700", "adjust": ""}
            return pd.DataFrame(
                [
                    {"date": "2026-02-27", "close": 500.0},
                    {"date": "2026-03-02", "close": 520.0},
                ]
            )

        @staticmethod
        def stock_us_hist(**kwargs):
            raise AssertionError("Eastmoney should be skipped after the circuit breaker opens")

        @staticmethod
        def stock_us_daily(**kwargs):
            assert kwargs == {"symbol": "AAPL", "adjust": ""}
            return pd.DataFrame(
                [
                    {"date": "2026-02-27", "close": 250.0},
                    {"date": "2026-03-02", "close": 260.0},
                ]
            )

    client = AkshareDataClient(api=FakeApi(), max_retries=0)

    hk_quotes = client.fetch_hk_quotes("00700", date(2026, 3, 1), date(2026, 3, 2))
    us_quotes = client.fetch_us_quotes("AAPL", date(2026, 3, 1), date(2026, 3, 2))

    assert hk_quotes[["date", "close"]].to_dict("records") == [
        {"date": date(2026, 3, 2), "close": 520.0}
    ]
    assert us_quotes[["date", "close"]].to_dict("records") == [
        {"date": date(2026, 3, 2), "close": 260.0}
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