"""Data synchronization orchestrator."""

from __future__ import annotations

import json
from datetime import date, timedelta

from loguru import logger

from src.config import AppConfig
from src.data.a_share import AShareFetcher
from src.data.fund import FundFetcher
from src.data.hk_us import HKUSFetcher
from src.data.news import NewsFetcher
from src.storage.database import Database
from src.storage.queries import QueryService
from src.utils.rate_limiter import RateLimiter


class DataSyncService:
    """Orchestrates periodic data synchronization for all markets."""

    def __init__(self, config: AppConfig, db: Database):
        self.config = config
        self.db = db
        self.queries = QueryService(db)
        self.a_share = AShareFetcher()
        self.fund = FundFetcher()
        self.hk_us = HKUSFetcher()
        self.news = NewsFetcher()
        self.limiter = RateLimiter(calls_per_second=1.5)

    def sync_all(self):
        """Run full data sync across all configured watchlist items."""
        logger.info("Starting full data sync...")
        self.sync_a_shares()
        self.sync_funds()
        self.sync_hk_stocks()
        self.sync_us_stocks()
        self.sync_news()
        logger.info("Full data sync complete.")

    def sync_a_shares(self):
        """Sync A-share stock data."""
        symbols = self.config.watchlist.a_shares
        if not symbols:
            return
        logger.info(f"Syncing {len(symbols)} A-share stocks...")
        for symbol in symbols:
            # Fetch quotes
            try:
                self.limiter.wait("akshare")
                last_date = self.queries.get_last_quote_date("a_share", symbol)
                start = last_date + timedelta(days=1)
                end = date.today()
                if start <= end:
                    df = self.a_share.fetch_quotes(symbol, start, end)
                    self.queries.upsert_quotes("a_share", symbol, df)
                    logger.info(f"  [{symbol}] quotes: {len(df)} rows")
            except Exception as e:
                logger.error(f"  [{symbol}] quotes failed: {e}")

            # Fetch fund flow
            try:
                self.limiter.wait("akshare")
                flow_df = self.a_share.fetch_fund_flow(symbol)
                self.queries.upsert_fund_flow(symbol, flow_df)
            except Exception as e:
                logger.error(f"  [{symbol}] fund flow failed: {e}")

            # Fetch financial indicators
            try:
                self.limiter.wait("akshare")
                fin_df = self.a_share.fetch_financial_indicators(symbol)
                if not fin_df.empty:
                    data = fin_df.head(4).to_dict(orient="records")
                    self.queries.save_financial_report(
                        symbol=symbol,
                        report_date=date.today(),
                        report_type="indicator",
                        data=data,
                    )
            except Exception as e:
                logger.error(f"  [{symbol}] financial indicators failed: {e}")

    def sync_funds(self):
        """Sync fund NAV data."""
        funds = self.config.watchlist.funds
        if not funds:
            return
        logger.info(f"Syncing {len(funds)} funds...")
        for fund_code in funds:
            try:
                self.limiter.wait("akshare")
                # Determine if it's an ETF (starts with 1 or 5) or open-end fund
                is_etf = fund_code.startswith(("1", "5"))
                if is_etf:
                    last_date = self.queries.get_last_quote_date("etf", fund_code)
                    start = last_date + timedelta(days=1)
                    end = date.today()
                    if start <= end:
                        df = self.fund.fetch_etf_hist(fund_code, start, end)
                        self.queries.upsert_quotes("etf", fund_code, df)
                        logger.info(f"  [ETF {fund_code}] quotes: {len(df)} rows")
                else:
                    df = self.fund.fetch_fund_nav(fund_code)
                    self.queries.upsert_fund_nav(fund_code, "open_fund", df)
                    logger.info(f"  [Fund {fund_code}] NAV: {len(df)} rows")
            except Exception as e:
                logger.error(f"  [{fund_code}] sync failed: {e}")
                continue

    def sync_hk_stocks(self):
        """Sync HK stock data."""
        symbols = self.config.watchlist.hk_stocks
        if not symbols:
            return
        logger.info(f"Syncing {len(symbols)} HK stocks...")
        for symbol in symbols:
            try:
                self.limiter.wait("akshare")
                last_date = self.queries.get_last_quote_date("hk", symbol)
                start = last_date + timedelta(days=1)
                end = date.today()
                if start <= end:
                    df = self.hk_us.fetch_hk_quotes(symbol, start, end)
                    self.queries.upsert_quotes("hk", symbol, df)
                    logger.info(f"  [HK {symbol}] quotes: {len(df)} rows")
            except Exception as e:
                logger.error(f"  [HK {symbol}] sync failed: {e}")
                continue

    def sync_us_stocks(self):
        """Sync US stock data."""
        symbols = self.config.watchlist.us_stocks
        if not symbols:
            return
        logger.info(f"Syncing {len(symbols)} US stocks...")
        for symbol in symbols:
            try:
                self.limiter.wait("akshare")
                last_date = self.queries.get_last_quote_date("us", symbol)
                start = last_date + timedelta(days=1)
                end = date.today()
                if start <= end:
                    df = self.hk_us.fetch_us_quotes(symbol, start, end)
                    self.queries.upsert_quotes("us", symbol, df)
                    logger.info(f"  [US {symbol}] quotes: {len(df)} rows")
            except Exception as e:
                logger.error(f"  [US {symbol}] sync failed: {e}")
                continue

    def sync_news(self):
        """Sync news data."""
        logger.info("Syncing news...")
        try:
            # CCTV news
            self.limiter.wait("akshare")
            cctv_df = self.news.fetch_cctv_news(date.today().strftime("%Y%m%d"))
            if not cctv_df.empty:
                cctv_df = cctv_df.rename(columns={"title": "title", "content": "content"})
                self.queries.save_news("cctv", None, cctv_df)
                logger.info(f"  CCTV news: {len(cctv_df)} items")
        except Exception as e:
            logger.error(f"  CCTV news sync failed: {e}")

        # Stock-specific news for A-shares
        for symbol in self.config.watchlist.a_shares[:5]:  # Limit to avoid rate limits
            try:
                self.limiter.wait("akshare")
                news_df = self.news.fetch_stock_news(symbol)
                if not news_df.empty:
                    self.queries.save_news("eastmoney", symbol, news_df)
                    logger.info(f"  [{symbol}] news: {len(news_df)} items")
            except Exception as e:
                logger.error(f"  [{symbol}] news sync failed: {e}")
