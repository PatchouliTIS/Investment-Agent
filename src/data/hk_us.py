"""Hong Kong and US stock data fetcher using AKShare."""

from __future__ import annotations

from datetime import date

import akshare as ak
import pandas as pd
from loguru import logger

from src.data.base import DataFetcher


class HKUSFetcher(DataFetcher):
    """Fetches HK and US stock data via AKShare."""

    def fetch_quotes(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Not directly used - use fetch_hk_quotes or fetch_us_quotes."""
        return pd.DataFrame()

    def fetch_latest(self, symbols: list[str]) -> pd.DataFrame:
        """Not directly used."""
        return pd.DataFrame()

    def fetch_hk_quotes(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Fetch HK stock daily OHLCV (前复权)."""
        try:
            df = ak.stock_hk_hist(
                symbol=symbol,
                period="daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="qfq",
            )
            if df.empty:
                return df
            df = df.rename(
                columns={
                    "日期": "date",
                    "开盘": "open",
                    "收盘": "close",
                    "最高": "high",
                    "最低": "low",
                    "成交量": "volume",
                    "成交额": "turnover",
                    "涨跌幅": "change_pct",
                }
            )
            df["date"] = pd.to_datetime(df["date"]).dt.date
            return df[["date", "open", "high", "low", "close", "volume", "turnover", "change_pct"]]
        except Exception as e:
            logger.error(f"Failed to fetch HK quotes for {symbol}: {e}")
            return pd.DataFrame()

    def fetch_us_quotes(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Fetch US stock daily OHLCV."""
        try:
            df = ak.stock_us_hist(
                symbol=symbol,
                period="daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="qfq",
            )
            if df.empty:
                return df
            df = df.rename(
                columns={
                    "日期": "date",
                    "开盘": "open",
                    "收盘": "close",
                    "最高": "high",
                    "最低": "low",
                    "成交量": "volume",
                    "成交额": "turnover",
                    "涨跌幅": "change_pct",
                }
            )
            df["date"] = pd.to_datetime(df["date"]).dt.date
            return df[["date", "open", "high", "low", "close", "volume", "turnover", "change_pct"]]
        except Exception as e:
            logger.error(f"Failed to fetch US quotes for {symbol}: {e}")
            return pd.DataFrame()

    def fetch_hk_spot(self) -> pd.DataFrame:
        """Fetch HK stock real-time spot data."""
        try:
            return ak.stock_hk_spot_em()
        except Exception as e:
            logger.error(f"Failed to fetch HK spot data: {e}")
            return pd.DataFrame()
