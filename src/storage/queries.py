"""Common database query patterns."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd
from loguru import logger
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.storage.database import Database
from src.storage.models import (
    AlertEvent,
    AnalysisReport,
    FinancialReport,
    FundFlow,
    FundNav,
    NewsItem,
    StockQuote,
)
from src.utils.chinese_calendar import shanghai_now, shanghai_today


class QueryService:
    """Provides common query operations on the database."""

    def __init__(self, db: Database):
        self.db = db

    # --- Stock Quotes ---

    def get_last_quote_date(self, market: str, symbol: str) -> date:
        """Find the most recent quote date for incremental sync."""
        with self.db.get_session() as session:
            result = (
                session.query(StockQuote.date)
                .filter(StockQuote.market == market, StockQuote.symbol == symbol)
                .order_by(StockQuote.date.desc())
                .first()
            )
            if result:
                return result[0]
            return shanghai_today() - timedelta(days=365)

    def upsert_quotes(self, market: str, symbol: str, df: pd.DataFrame):
        """Insert new quotes, skip existing duplicates."""
        if df.empty:
            return
        with self.db.get_session() as session:
            for _, row in df.iterrows():
                stmt = sqlite_insert(StockQuote).values(
                    market=market,
                    symbol=symbol,
                    date=row["date"],
                    open=row.get("open"),
                    high=row.get("high"),
                    low=row.get("low"),
                    close=row.get("close"),
                    volume=row.get("volume"),
                    turnover=row.get("turnover"),
                    change_pct=row.get("change_pct"),
                ).on_conflict_do_nothing(
                    index_elements=["market", "symbol", "date"]
                )
                session.execute(stmt)
            session.commit()
            logger.debug(f"Upserted {len(df)} quotes for {market}/{symbol}")

    def get_quotes(
        self, market: str, symbol: str, start: date, end: date
    ) -> pd.DataFrame:
        """Retrieve historical quotes as DataFrame."""
        with self.db.get_session() as session:
            results = (
                session.query(StockQuote)
                .filter(
                    StockQuote.market == market,
                    StockQuote.symbol == symbol,
                    StockQuote.date >= start,
                    StockQuote.date <= end,
                )
                .order_by(StockQuote.date)
                .all()
            )
            if not results:
                return pd.DataFrame()
            data = [
                {
                    "date": r.date,
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "volume": r.volume,
                    "turnover": r.turnover,
                    "change_pct": r.change_pct,
                }
                for r in results
            ]
            return pd.DataFrame(data)

    # --- Fund NAV ---

    def upsert_fund_nav(self, fund_code: str, fund_type: str, df: pd.DataFrame):
        """Insert fund NAV records."""
        if df.empty:
            return
        with self.db.get_session() as session:
            for _, row in df.iterrows():
                stmt = sqlite_insert(FundNav).values(
                    fund_code=fund_code,
                    fund_type=fund_type,
                    date=row["date"],
                    nav=row.get("nav"),
                    acc_nav=row.get("acc_nav"),
                    daily_return=row.get("daily_return"),
                ).on_conflict_do_nothing(
                    index_elements=["fund_code", "date"]
                )
                session.execute(stmt)
            session.commit()
            logger.debug(f"Upserted {len(df)} NAV records for {fund_code}")

    def get_last_fund_nav_date(self, fund_code: str) -> date:
        """Find the newest NAV date for incremental fund synchronization."""
        with self.db.get_session() as session:
            result = (
                session.query(FundNav.date)
                .filter(FundNav.fund_code == fund_code)
                .order_by(FundNav.date.desc())
                .first()
            )
            if result:
                return result[0]
            return shanghai_today() - timedelta(days=365)

    # --- Fund Flow ---

    def upsert_fund_flow(self, symbol: str, df: pd.DataFrame):
        """Insert fund flow records."""
        if df.empty:
            return
        with self.db.get_session() as session:
            for _, row in df.iterrows():
                stmt = sqlite_insert(FundFlow).values(
                    symbol=symbol,
                    date=row["date"],
                    main_net_inflow=row.get("main_net_inflow"),
                    small_net_inflow=row.get("small_net_inflow"),
                    total_net_inflow=row.get("total_net_inflow"),
                ).on_conflict_do_nothing(
                    index_elements=["symbol", "date"]
                )
                session.execute(stmt)
            session.commit()

    # --- Financial Reports ---

    def save_financial_report(
        self, symbol: str, report_date: date, report_type: str, data: dict
    ):
        """Save financial report as JSON."""
        with self.db.get_session() as session:
            stmt = sqlite_insert(FinancialReport).values(
                symbol=symbol,
                report_date=report_date,
                report_type=report_type,
                data_json=json.dumps(data, ensure_ascii=False, default=str),
                fetched_at=shanghai_now(),
            ).on_conflict_do_nothing(
                index_elements=["symbol", "report_date", "report_type"]
            )
            session.execute(stmt)
            session.commit()

    def get_latest_financial_report(self, symbol: str) -> dict | None:
        """Get the most recent financial indicators for a symbol."""
        with self.db.get_session() as session:
            result = (
                session.query(FinancialReport)
                .filter(
                    FinancialReport.symbol == symbol,
                    FinancialReport.report_type == "indicator",
                )
                .order_by(FinancialReport.report_date.desc())
                .first()
            )
            if result and result.data_json:
                return json.loads(result.data_json)
            return None

    # --- News ---

    def save_news(self, source: str, symbol: str | None, items: pd.DataFrame):
        """Save news items."""
        if items.empty:
            return
        with self.db.get_session() as session:
            for _, row in items.iterrows():
                news = NewsItem(
                    source=source,
                    symbol=symbol,
                    title=row.get("title", ""),
                    content=row.get("content", ""),
                    url=row.get("url", ""),
                    published_at=pd.to_datetime(row.get("published_at")) if row.get("published_at") else None,
                    fetched_at=shanghai_now(),
                )
                session.add(news)
            session.commit()

    def get_recent_news(self, symbol: str, days: int = 7) -> list[dict]:
        """Get recent news for a symbol."""
        cutoff = shanghai_now() - timedelta(days=days)
        with self.db.get_session() as session:
            results = (
                session.query(NewsItem)
                .filter(
                    NewsItem.symbol == symbol,
                    NewsItem.fetched_at >= cutoff,
                )
                .order_by(NewsItem.published_at.desc())
                .limit(50)
                .all()
            )
            return [
                {"title": r.title, "content": r.content, "published_at": str(r.published_at)}
                for r in results
            ]

    # --- Analysis Reports ---

    def save_analysis_report(self, report_type: str, scope: str, content: dict, llm_model: str):
        """Save an analysis report."""
        with self.db.get_session() as session:
            report = AnalysisReport(
                report_type=report_type,
                scope=scope,
                content_json=json.dumps(content, ensure_ascii=False, default=str),
                llm_model=llm_model,
                created_at=shanghai_now(),
            )
            session.add(report)
            session.commit()

    # --- Alerts ---

    def save_alert_if_new(
        self, symbol: str, alert_type: str, alert_date: date, message: str
    ) -> bool:
        """Persist an alert once per symbol/type/trading day.

        Returns ``True`` only when the alert was newly recorded and should be sent.
        """
        with self.db.get_session() as session:
            stmt = sqlite_insert(AlertEvent).values(
                symbol=symbol,
                alert_type=alert_type,
                date=alert_date,
                message=message,
                created_at=shanghai_now(),
            ).on_conflict_do_nothing(
                index_elements=["symbol", "alert_type", "date"]
            )
            result = session.execute(stmt)
            session.commit()
            return result.rowcount > 0
