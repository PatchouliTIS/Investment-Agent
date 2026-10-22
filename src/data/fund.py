"""Fund and ETF data fetcher using AKShare."""

from __future__ import annotations

from datetime import date

import akshare as ak
import pandas as pd
from loguru import logger

from src.data.base import DataFetcher


class FundFetcher(DataFetcher):
    """Fetches fund (公募/ETF) data via AKShare."""

    def fetch_quotes(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Fetch fund NAV history."""
        return self.fetch_fund_nav(symbol)

    def fetch_latest(self, symbols: list[str]) -> pd.DataFrame:
        """Fetch latest NAV for multiple funds."""
        results = []
        for code in symbols:
            try:
                df = self.fetch_fund_nav(code)
                if not df.empty:
                    latest = df.iloc[-1:].copy()
                    latest["fund_code"] = code
                    results.append(latest)
            except Exception as e:
                logger.error(f"Failed to fetch latest NAV for {code}: {e}")
        return pd.concat(results) if results else pd.DataFrame()

    def fetch_fund_nav(self, fund_code: str) -> pd.DataFrame:
        """Fetch open-end fund NAV history (单位净值走势)."""
        try:
            df = ak.fund_open_fund_info_em(fund=fund_code, indicator="单位净值走势")
            if df.empty:
                return df
            df = df.rename(
                columns={
                    "净值日期": "date",
                    "单位净值": "nav",
                    "日增长率": "daily_return",
                }
            )
            df["date"] = pd.to_datetime(df["date"]).dt.date
            df["acc_nav"] = df["nav"]  # Will be overridden if available
            return df[["date", "nav", "acc_nav", "daily_return"]]
        except Exception as e:
            logger.error(f"Failed to fetch fund NAV for {fund_code}: {e}")
            return pd.DataFrame()

    def fetch_etf_hist(self, fund_code: str, start: date, end: date) -> pd.DataFrame:
        """Fetch ETF historical price data (Sina; full history filtered locally).

        Volume is converted from 份 to 手 to match the stock quote convention.
        """
        try:
            prefixed = f"{'sh' if fund_code.startswith('5') else 'sz'}{fund_code}"
            df = ak.fund_etf_hist_sina(symbol=prefixed)
            if df.empty:
                return df
            df["date"] = pd.to_datetime(df["date"]).dt.date
            df = df[(df["date"] >= start) & (df["date"] <= end)]
            if df.empty:
                return df
            df["volume"] = df["volume"] / 100  # 份 -> 手
            df = df.rename(columns={"amount": "turnover"})
            return df[["date", "open", "high", "low", "close", "volume", "turnover"]]
        except Exception as e:
            logger.error(f"Failed to fetch ETF history for {fund_code}: {e}")
            return pd.DataFrame()
