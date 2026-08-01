"""Tests for provider symbol mapping and proxy isolation."""

import os
from datetime import date

import pandas as pd
import pytest

from src.data.akshare_client import AkshareDataClient, BeijingExchangeUnsupportedError


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
