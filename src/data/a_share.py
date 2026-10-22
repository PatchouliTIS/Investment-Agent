"""A-share stock data fetcher using AKShare."""

from __future__ import annotations

from datetime import date

import akshare as ak
import pandas as pd
from loguru import logger

from src.data.base import DataFetcher
from src.utils.retry import retry_on_network_error


class AShareFetcher(DataFetcher):
    """Fetches A-share market data via AKShare.

    Quotes use Tencent as the primary source with Sina as fallback, because
    the EastMoney kline endpoint intermittently drops connections from some
    networks. Volumes are normalized to 手 (lots of 100 shares), matching
    the historical EastMoney convention already stored in the DB.
    """

    @retry_on_network_error()
    def fetch_quotes(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Fetch daily OHLCV data (前复权), Tencent first, Sina fallback."""
        try:
            return self._fetch_quotes_tx(symbol, start, end)
        except Exception as e:
            logger.warning(f"Tencent quotes failed for {symbol}: {e}; falling back to Sina")
            return self._fetch_quotes_sina(symbol, start, end)

    @retry_on_network_error()
    def fetch_latest(self, symbols: list[str]) -> pd.DataFrame:
        """Fetch real-time spot data for A-shares (Sina full-market snapshot)."""
        df = ak.stock_zh_a_spot()
        if df.empty:
            return df
        df = df.rename(
            columns={
                "名称": "name",
                "最新价": "close",
                "涨跌幅": "change_pct",
                "成交量": "volume",
                "成交额": "turnover",
            }
        )
        df["symbol"] = df["代码"].str[2:]  # strip sh/sz prefix
        df["volume"] = df["volume"] / 100  # 股 -> 手
        df = df[df["symbol"].isin(symbols)]
        return df[["symbol", "name", "close", "change_pct", "volume", "turnover"]]

    @staticmethod
    def _infer_market(symbol: str) -> str:
        """Infer market from A-share symbol prefix."""
        if symbol.startswith(("6", "9")):
            return "sh"
        return "sz"

    def _prefixed(self, symbol: str) -> str:
        return f"{self._infer_market(symbol)}{symbol}"

    def _fetch_quotes_tx(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Tencent daily bars (前复权). Columns: date/open/close/high/low/amount(手)."""
        df = ak.stock_zh_a_hist_tx(
            symbol=self._prefixed(symbol),
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="qfq",
        )
        if df.empty:
            return df
        df = df.rename(columns={"amount": "volume"})
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df["turnover"] = None  # Tencent endpoint provides no turnover
        df["change_pct"] = (df["close"].pct_change() * 100).round(2)
        return df[["date", "open", "high", "low", "close", "volume", "turnover", "change_pct"]]

    def _fetch_quotes_sina(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Sina daily bars (前复权). Volume converted from 股 to 手."""
        df = ak.stock_zh_a_daily(
            symbol=self._prefixed(symbol),
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
            adjust="qfq",
        )
        if df.empty:
            return df
        df["volume"] = df["volume"] / 100  # 股 -> 手
        df = df.rename(columns={"amount": "turnover"})
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df["change_pct"] = (df["close"].pct_change() * 100).round(2)
        return df[["date", "open", "high", "low", "close", "volume", "turnover", "change_pct"]]

    @retry_on_network_error()
    def fetch_fund_flow(self, symbol: str) -> pd.DataFrame:
        """Fetch individual stock money flow (资金流向, EastMoney)."""
        market = self._infer_market(symbol)
        df = ak.stock_individual_fund_flow(stock=symbol, market=market)
        if df.empty:
            return df
        df = df.rename(
            columns={
                "日期": "date",
                "主力净流入-净额": "main_net_inflow",
                "小单净流入-净额": "small_net_inflow",
            }
        )
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df["total_net_inflow"] = df.get("main_net_inflow", 0) + df.get(
            "small_net_inflow", 0
        )
        return df[["date", "main_net_inflow", "small_net_inflow", "total_net_inflow"]]

    @retry_on_network_error()
    def fetch_financial_indicators(self, symbol: str) -> pd.DataFrame:
        """Fetch key financial indicators (财务指标, EastMoney)."""
        return ak.stock_financial_analysis_indicator(symbol=symbol)
