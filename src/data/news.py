"""News and sentiment data fetcher using AKShare."""

from __future__ import annotations

from datetime import date

import akshare as ak
import pandas as pd
from loguru import logger


class NewsFetcher:
    """Fetches market news from various sources."""

    def fetch_cctv_news(self, date_str: str) -> pd.DataFrame:
        """Fetch CCTV financial news for a given date."""
        try:
            df = ak.news_cctv(date=date_str)
            return df
        except Exception as e:
            logger.error(f"Failed to fetch CCTV news for {date_str}: {e}")
            return pd.DataFrame()

    def fetch_stock_news(self, symbol: str) -> pd.DataFrame:
        """Fetch stock-specific news from EastMoney."""
        try:
            df = ak.stock_news_em(symbol=symbol)
            if df.empty:
                return df
            df = df.rename(
                columns={
                    "新闻标题": "title",
                    "新闻内容": "content",
                    "新闻链接": "url",
                    "发布时间": "published_at",
                }
            )
            return df[["title", "content", "url", "published_at"]]
        except Exception as e:
            logger.error(f"Failed to fetch stock news for {symbol}: {e}")
            return pd.DataFrame()

    def fetch_hot_rank(self) -> pd.DataFrame:
        """Fetch currently trending/hot stocks."""
        try:
            return ak.stock_hot_rank_em()
        except Exception as e:
            logger.error(f"Failed to fetch hot rank: {e}")
            return pd.DataFrame()
