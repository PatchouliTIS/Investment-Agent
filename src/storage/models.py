"""SQLAlchemy ORM models for all database tables."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class StockQuote(Base):
    """Historical and daily price data for all markets."""

    __tablename__ = "stock_quotes"
    __table_args__ = (
        UniqueConstraint("market", "symbol", "date", name="uq_quote_market_symbol_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    market = Column(String(10), nullable=False, index=True)  # a_share, hk, us
    symbol = Column(String(20), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    turnover = Column(Float)
    change_pct = Column(Float)


class FundNav(Base):
    """Fund NAV tracking."""

    __tablename__ = "fund_nav"
    __table_args__ = (
        UniqueConstraint("fund_code", "date", name="uq_fund_nav_code_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    fund_code = Column(String(20), nullable=False, index=True)
    fund_type = Column(String(20))  # open_fund, etf
    date = Column(Date, nullable=False, index=True)
    nav = Column(Float)
    acc_nav = Column(Float)
    daily_return = Column(Float)


class FundFlow(Base):
    """Money flow data for A-shares."""

    __tablename__ = "fund_flow"
    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_fund_flow_symbol_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    main_net_inflow = Column(Float)
    small_net_inflow = Column(Float)
    total_net_inflow = Column(Float)


class FinancialReport(Base):
    """Financial statements stored as JSON."""

    __tablename__ = "financial_reports"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "report_date", "report_type", name="uq_fin_report_symbol_date_type"
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    report_date = Column(Date, nullable=False)
    report_type = Column(String(30), nullable=False)  # balance_sheet, income, cash_flow, indicator
    data_json = Column(Text)
    fetched_at = Column(DateTime, default=datetime.now)


class NewsItem(Base):
    """News articles for sentiment analysis."""

    __tablename__ = "news"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(50), nullable=False)
    symbol = Column(String(20), nullable=True, index=True)
    title = Column(String(500))
    content = Column(Text)
    url = Column(String(500))
    published_at = Column(DateTime, index=True)
    fetched_at = Column(DateTime, default=datetime.now)


class AnalysisReport(Base):
    """AI-generated analysis reports."""

    __tablename__ = "analysis_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_type = Column(String(50), nullable=False)  # daily_brief, weekly_deep, alert
    scope = Column(String(50))  # portfolio, symbol, market
    content_json = Column(Text)
    llm_model = Column(String(100))
    created_at = Column(DateTime, default=datetime.now, index=True)


class Portfolio(Base):
    """User's current holdings (manually maintained)."""

    __tablename__ = "portfolio"
    __table_args__ = (
        UniqueConstraint("market", "symbol", name="uq_portfolio_market_symbol"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    market = Column(String(10), nullable=False)
    symbol = Column(String(20), nullable=False)
    name = Column(String(100))
    shares = Column(Float)
    cost_price = Column(Float)
    updated_at = Column(DateTime, default=datetime.now)
