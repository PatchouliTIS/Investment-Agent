"""Tests for provider symbol mapping and proxy isolation."""

import os
from datetime import date, timedelta

import pandas as pd
import pytest

from src.data.akshare_client import AkshareDataClient, BeijingExchangeUnsupportedError
from src.utils.chinese_calendar import shanghai_today


class StubApi:
    """Record which provider was called with which symbol."""

    def __init__(self):
        self.calls = []

    def _record(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return pd.DataFrame()

    def stock_zh_a_hist(self, **kwargs):
        raise ValueError("eastmoney unavailable")

    def stock_zh_a_daily(self, **kwargs):
        return self._record("sina", **kwargs)

    def stock_zh_a_hist_tx(self, **kwargs):
        return self._record("tencent", **kwargs)

    def stock_individual_fund_flow(self, **kwargs):
        return self._record("fund_flow", **kwargs)


def _client(api=None):
    return AkshareDataClient(api=api or StubApi(), max_retries=0, retry_delay_seconds=0.0)


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("600519", "sh600519"),
        ("000858", "sz000858"),
        ("900901", "sh900901"),  # Shanghai B-share keeps the sh prefix.
        ("830839", "bj830839"),
        ("920002", "bj920002"),  # Would match the Shanghai "9" rule without the BSE check.
        ("430047", "bj430047"),
        ("871981", "bj871981"),
    ],
)
def test_provider_symbol_covers_all_boards(symbol, expected):
    assert AkshareDataClient._a_share_provider_symbol(symbol) == expected


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [("600519", "sh"), ("000858", "sz"), ("830839", "bj"), ("920002", "bj")],
)
def test_fund_flow_market_covers_all_boards(symbol, expected):
    assert AkshareDataClient._fund_flow_market(symbol) == expected


def test_bse_fallback_fails_fast_without_calling_sina_or_tencent():
    """Neither fallback serves the BSE, so the run must not waste requests on them."""
    api = StubApi()
    client = _client(api)

    with pytest.raises(BeijingExchangeUnsupportedError, match="Beijing Stock Exchange"):
        client.fetch_a_share_quotes("830839", date(2026, 7, 1), date(2026, 7, 31))

    assert api.calls == []


def test_shanghai_symbol_still_reaches_the_fallback_chain():
    """The fast-fail must not affect boards the fallbacks do serve."""
    api = StubApi()
    client = _client(api)

    client.fetch_a_share_quotes("600519", date(2026, 7, 1), date(2026, 7, 31))

    assert [name for name, _ in api.calls] == ["sina"]
    assert api.calls[0][1]["symbol"] == "sh600519"


def test_direct_connection_bypasses_system_proxy(monkeypatch):
    """use_env_proxy=False must survive urllib's fallback to OS proxy settings."""
    # Clear any host-level proxy variables so the test is hermetic.
    for variable in ("NO_PROXY", "no_proxy", "HTTPS_PROXY", "ALL_PROXY", "SOCKS_PROXY"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:7897")
    monkeypatch.setenv("socks_proxy", "socks://127.0.0.1:7897")
    seen = {}

    class ProxyProbeApi(StubApi):
        def stock_zh_a_daily(self, **kwargs):
            seen["no_proxy"] = os.environ.get("NO_PROXY")
            seen["https_proxy"] = os.environ.get("https_proxy")
            seen["socks_proxy"] = os.environ.get("socks_proxy")
            return pd.DataFrame()

    client = AkshareDataClient(
        api=ProxyProbeApi(), use_env_proxy=False, max_retries=0, retry_delay_seconds=0.0
    )
    client.fetch_a_share_quotes("600519", date(2026, 7, 1), date(2026, 7, 31))

    assert seen["no_proxy"] == "*"
    assert seen["https_proxy"] is None
    assert seen["socks_proxy"] is None
    # The caller's environment is restored afterwards.
    assert os.environ["https_proxy"] == "http://127.0.0.1:7897"
    assert os.environ["socks_proxy"] == "socks://127.0.0.1:7897"
    assert "NO_PROXY" not in os.environ


def test_env_proxy_mode_leaves_environment_untouched(monkeypatch):
    for variable in ("NO_PROXY", "no_proxy", "HTTPS_PROXY", "ALL_PROXY", "SOCKS_PROXY"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:7897")
    seen = {}

    class ProxyProbeApi(StubApi):
        def stock_zh_a_daily(self, **kwargs):
            seen["https_proxy"] = os.environ.get("https_proxy")
            seen["no_proxy"] = os.environ.get("NO_PROXY")
            return pd.DataFrame()

    client = AkshareDataClient(
        api=ProxyProbeApi(), use_env_proxy=True, max_retries=0, retry_delay_seconds=0.0
    )
    client.fetch_a_share_quotes("600519", date(2026, 7, 1), date(2026, 7, 31))

    assert seen["https_proxy"] == "http://127.0.0.1:7897"
    assert seen["no_proxy"] is None


def test_etf_fallback_prefers_tencent_adjusted_series():
    """Sina's ETF history is unadjusted, so the fallback chain must try Tencent first."""
    api = StubApi()
    client = _client(api)
    client._eastmoney_kline_available = False  # Force the fallback chain.

    client.fetch_fund_nav("512480", date(2026, 1, 1), date(2026, 12, 31))

    assert [name for name, _ in api.calls] == ["tencent"]
    assert api.calls[0][1]["symbol"] == "sh512480"
    assert api.calls[0][1]["adjust"] == "qfq"


def test_etf_fallback_uses_sina_only_when_tencent_fails():
    """Sina remains the last resort when Tencent cannot serve the ETF."""

    class TencentDownApi(StubApi):
        def stock_zh_a_hist_tx(self, **kwargs):
            raise ValueError("tencent unavailable")

        def fund_etf_hist_sina(self, **kwargs):
            return self._record("sina_etf", **kwargs)

    api = TencentDownApi()
    client = _client(api)
    client._eastmoney_kline_available = False

    client.fetch_fund_nav("512480", date(2026, 1, 1), date(2026, 12, 31))

    assert [name for name, _ in api.calls] == ["sina_etf"]
    assert api.calls[0][1]["symbol"] == "sh512480"


def test_a_share_fallback_uses_ths_after_sina_and_tencent_fail(monkeypatch):
    """The THS JSONP feed is parsed and clipped to the requested date window."""

    class AllDownApi(StubApi):
        def stock_zh_a_daily(self, **kwargs):
            self.calls.append(("sina", kwargs))
            raise ValueError("sina unavailable")

        def stock_zh_a_hist_tx(self, **kwargs):
            self.calls.append(("tencent", kwargs))
            raise ValueError("tencent unavailable")

    rows = ";".join(
        [
            "20260630,10,11,9,10,100,1000,0,0,0,0",
            "20260701,11,12,10,11,200,2200,0,0,0,0",
            "20260801,12,13,11,12,300,3600,0,0,0,0",
        ]
    )

    class StubResponse:
        text = f'quotebridge({{"data":"{rows}"}})'

        @staticmethod
        def raise_for_status():
            return None

    seen = {}

    def stub_get(url, headers, timeout):
        seen.update(url=url, headers=headers, timeout=timeout)
        return StubResponse()

    monkeypatch.setattr("src.data.akshare_client.requests.get", stub_get)
    api = AllDownApi()
    client = _client(api)

    result = client.fetch_a_share_quotes("600519", date(2026, 7, 1), date(2026, 7, 31))

    assert [name for name, _ in api.calls] == ["sina", "tencent"]
    assert seen["url"] == "https://d.10jqka.com.cn/v6/line/hs_600519/01/last1800.js"
    assert seen["headers"]["Referer"] == "https://stockpage.10jqka.com.cn/600519/"
    assert seen["timeout"] == 20
    assert result.to_dict("records") == [
        {
            "date": date(2026, 7, 1),
            "open": 11.0,
            "high": 12.0,
            "low": 10.0,
            "close": 11.0,
            "volume": 200.0,
            "turnover": 2200.0,
            "change_pct": 10.0,
        }
    ]


def test_missing_tencent_volume_is_preserved_as_missing():
    """Price-only Tencent responses remain usable without inventing volume data."""
    raw = pd.DataFrame(
        {
            "date": ["2026-07-01"],
            "open": [10],
            "high": [12],
            "low": [9],
            "close": [11],
            "amount": [2200],
        }
    )

    result = AkshareDataClient._normalize_quotes(raw)

    assert pd.isna(result.iloc[0]["volume"])
    assert result.iloc[0]["turnover"] == 2200


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_MARKET_INTEGRATION") != "1",
    reason="Set RUN_MARKET_INTEGRATION=1 to query the public THS history endpoint.",
)
def test_ths_fallback_returns_three_month_history(monkeypatch):
    """Exercise the real THS fallback while disabling the preceding providers locally."""
    client = AkshareDataClient(max_retries=0, retry_delay_seconds=0.0)

    def provider_unavailable(**_kwargs):
        raise ValueError("provider disabled to exercise the THS fallback")

    monkeypatch.setattr(client.api, "stock_zh_a_hist", provider_unavailable)
    monkeypatch.setattr(client.api, "stock_zh_a_daily", provider_unavailable)
    monkeypatch.setattr(client.api, "stock_zh_a_hist_tx", provider_unavailable)
    end = shanghai_today()
    start = end - timedelta(days=92)

    result = client.fetch_a_share_quotes("600519", start, end)

    assert len(result) >= 40
    assert result["date"].is_unique
    assert result[["open", "high", "low", "close"]].notna().all().all()
    assert result["date"].min() >= start
    assert result["date"].max() <= end
