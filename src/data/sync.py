"""Incremental persistence of market data for the configured watchlist."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pandas as pd
from loguru import logger

from src.config import AppConfig
from src.data.akshare_client import AkshareDataClient
from src.storage.database import Database
from src.storage.queries import QueryService
from src.utils.chinese_calendar import shanghai_today


class DataSyncService:
    """Synchronize watchlist data without letting one provider failure stop the run."""

    def __init__(
        self,
        config: AppConfig,
        db: Database,
        client: AkshareDataClient | None = None,
    ):
        self.config = config
        self.queries = QueryService(db)
        self.client = client or AkshareDataClient()

    def sync_all(self) -> dict[str, int]:
        """Synchronize each configured market and return inserted-record counts."""
        summary = {"a_share_quotes": 0, "fund_nav": 0, "hk_quotes": 0, "us_quotes": 0}

        for symbol in self.config.watchlist.a_shares:
            summary["a_share_quotes"] += self._sync_quotes(
                "a_share", symbol, self.client.fetch_a_share_quotes
            )
            self._sync_a_share_enrichment(symbol)

        for fund_code in self.config.watchlist.funds:
            summary["fund_nav"] += self._sync_fund(fund_code)

        for symbol in self.config.watchlist.hk_stocks:
            summary["hk_quotes"] += self._sync_quotes("hk", symbol, self.client.fetch_hk_quotes)

        for symbol in self.config.watchlist.us_stocks:
            summary["us_quotes"] += self._sync_quotes("us", symbol, self.client.fetch_us_quotes)

        logger.info(f"Data sync complete: {summary}")
        return summary

    def _sync_quotes(
        self,
        market: str,
        symbol: str,
        fetcher: Callable[[str, date, date], pd.DataFrame],
    ) -> int:
        start = self.queries.get_last_quote_date(market, symbol)
        try:
            quotes = fetcher(symbol, start, shanghai_today())
            self.queries.upsert_quotes(market, symbol, quotes)
            logger.info(f"Synced {len(quotes)} {market} quote rows for {symbol}")
            return len(quotes)
        except Exception as error:  # noqa: BLE001
            logger.error(f"Failed to sync {market} quotes for {symbol}: {error}")
            return 0

    def _sync_fund(self, fund_code: str) -> int:
        start = self.queries.get_last_fund_nav_date(fund_code)
        try:
            nav = self.client.fetch_fund_nav(fund_code, start, shanghai_today())
            fund_type = "etf" if fund_code.startswith(("15", "16", "51", "52", "56", "58", "59")) else "open_fund"
            self.queries.upsert_fund_nav(fund_code, fund_type, nav)
            logger.info(f"Synced {len(nav)} fund NAV rows for {fund_code}")
            return len(nav)
        except Exception as error:  # noqa: BLE001
            logger.error(f"Failed to sync fund NAV for {fund_code}: {error}")
            return 0

    def _sync_a_share_enrichment(self, symbol: str) -> None:
        self._run_enrichment(symbol, "financial indicators", self._save_financial_indicators)
        self._run_enrichment(symbol, "fund flow", self._save_fund_flow)
        self._run_enrichment(symbol, "news", self._save_news)

    def _run_enrichment(
        self,
        symbol: str,
        name: str,
        action: Callable[[str], None],
    ) -> None:
        try:
            action(symbol)
        except Exception as error:  # noqa: BLE001
            logger.warning(f"Failed to sync {name} for {symbol}: {error}")

    def _save_financial_indicators(self, symbol: str) -> None:
        result = self.client.fetch_latest_financial_indicators(symbol)
        if result is None:
            return
        report_date, indicators = result
        self.queries.save_financial_report(symbol, report_date, "indicator", indicators)

    def _save_fund_flow(self, symbol: str) -> None:
        self.queries.upsert_fund_flow(symbol, self.client.fetch_fund_flow(symbol))

    def _save_news(self, symbol: str) -> None:
        self.queries.save_news("akshare", symbol, self.client.fetch_news(symbol))