"""Common database query patterns."""

from __future__ import annotations

import json
from collections import defaultdict
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
    Portfolio,
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

    def get_fund_nav(self, fund_code: str, start: date, end: date) -> pd.DataFrame:
        """Retrieve a fund's historical NAV series as a DataFrame."""
        with self.db.get_session() as session:
            results = (
                session.query(FundNav)
                .filter(
                    FundNav.fund_code == fund_code,
                    FundNav.date >= start,
                    FundNav.date <= end,
                )
                .order_by(FundNav.date)
                .all()
            )
            if not results:
                return pd.DataFrame()
            return pd.DataFrame(
                [
                    {
                        "date": record.date,
                        "nav": record.nav,
                        "acc_nav": record.acc_nav,
                        "daily_return": record.daily_return,
                        "fund_type": record.fund_type,
                    }
                    for record in results
                ]
            )

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

    # --- Portfolio Holdings and Valuation ---

    def upsert_portfolio_holding(
        self,
        market: str,
        symbol: str,
        name: str,
        shares: float,
        cost_price: float,
    ) -> None:
        """Create or update a manually maintained holding."""
        if market not in {"a_share", "fund", "hk", "us"}:
            raise ValueError(f"Unsupported holding market: {market}")
        if shares < 0:
            raise ValueError("Holding shares cannot be negative")
        if cost_price < 0:
            raise ValueError("Holding cost price cannot be negative")

        with self.db.get_session() as session:
            stmt = sqlite_insert(Portfolio).values(
                market=market,
                symbol=symbol,
                name=name,
                shares=shares,
                cost_price=cost_price,
                updated_at=shanghai_now(),
            ).on_conflict_do_update(
                index_elements=["market", "symbol"],
                set_={
                    "name": name,
                    "shares": shares,
                    "cost_price": cost_price,
                    "updated_at": shanghai_now(),
                },
            )
            session.execute(stmt)
            session.commit()

    def delete_portfolio_holding(self, market: str, symbol: str) -> bool:
        """Delete one holding identified by its market and symbol."""
        with self.db.get_session() as session:
            deleted_count = (
                session.query(Portfolio)
                .filter(Portfolio.market == market, Portfolio.symbol == symbol)
                .delete(synchronize_session=False)
            )
            session.commit()
            return deleted_count > 0

    def get_portfolio_valuation(self) -> dict:
        """Value all holdings using the latest locally synchronized prices.

        Values are grouped by currency because CNY, HKD, and USD must not be
        summed without an explicit foreign-exchange conversion source.
        """
        with self.db.get_session() as session:
            holdings = session.query(Portfolio).order_by(Portfolio.market, Portfolio.symbol).all()
            valued_holdings = [self._value_holding(session, holding) for holding in holdings]

        totals: dict[str, dict] = defaultdict(
            lambda: {
                "market_value": 0.0,
                "cost_value": 0.0,
                "unrealized_pnl": 0.0,
                "valued_count": 0,
            }
        )
        unvalued_count = 0
        for holding in valued_holdings:
            if holding["market_value"] is None:
                unvalued_count += 1
                continue

            total = totals[holding["currency"]]
            total["market_value"] += holding["market_value"]
            total["cost_value"] += holding["cost_value"]
            total["unrealized_pnl"] += holding["unrealized_pnl"]
            total["valued_count"] += 1

        by_currency = []
        for currency, total in sorted(totals.items()):
            total["currency"] = currency
            total["unrealized_pnl_pct"] = (
                total["unrealized_pnl"] / total["cost_value"] * 100
                if total["cost_value"]
                else None
            )
            by_currency.append(total)

        return {
            "holdings": valued_holdings,
            "by_currency": by_currency,
            "unvalued_count": unvalued_count,
        }

    @staticmethod
    def _market_currency(market: str) -> str:
        return {"a_share": "CNY", "fund": "CNY", "hk": "HKD", "us": "USD"}[market]

    def _value_holding(self, session, holding: Portfolio) -> dict:
        """Return a holding enriched with its latest local market price."""
        if holding.market == "fund":
            latest = (
                session.query(FundNav.nav, FundNav.date)
                .filter(FundNav.fund_code == holding.symbol)
                .order_by(FundNav.date.desc())
                .first()
            )
        else:
            latest = (
                session.query(StockQuote.close, StockQuote.date)
                .filter(StockQuote.market == holding.market, StockQuote.symbol == holding.symbol)
                .order_by(StockQuote.date.desc())
                .first()
            )

        shares = float(holding.shares or 0)
        cost_price = float(holding.cost_price or 0)
        valuation = {
            "market": holding.market,
            "symbol": holding.symbol,
            "name": holding.name or holding.symbol,
            "shares": shares,
            "cost_price": cost_price,
            "currency": self._market_currency(holding.market),
            "latest_price": None,
            "price_date": None,
            "cost_value": shares * cost_price,
            "market_value": None,
            "unrealized_pnl": None,
            "unrealized_pnl_pct": None,
        }
        if latest is None or latest[0] is None:
            return valuation

        latest_price, price_date = latest
        market_value = shares * float(latest_price)
        unrealized_pnl = market_value - valuation["cost_value"]
        valuation.update(
            {
                "latest_price": float(latest_price),
                "price_date": price_date.isoformat(),
                "market_value": market_value,
                "unrealized_pnl": unrealized_pnl,
                "unrealized_pnl_pct": (
                    unrealized_pnl / valuation["cost_value"] * 100
                    if valuation["cost_value"]
                    else None
                ),
            }
        )
        return valuation
