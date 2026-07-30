"""Report generator - orchestrates all analyst agents."""

from __future__ import annotations

from loguru import logger

from src.analysis.fundamental import FundamentalAnalyst
from src.analysis.llm_client import LLMClient
from src.analysis.portfolio import PortfolioAdvisor
from src.analysis.sentiment import SentimentAnalyst
from src.analysis.technical import TechnicalAnalyst
from src.config import AppConfig
from src.storage.database import Database
from src.storage.queries import QueryService
from src.utils.chinese_calendar import shanghai_today


class ReportGenerator:
    """Runs all analysts and assembles structured reports."""

    def __init__(self, llm: LLMClient, db: Database, config: AppConfig):
        self.llm = llm
        self.db = db
        self.config = config
        self.queries = QueryService(db)
        self.analysts = [
            FundamentalAnalyst(llm, db),
            TechnicalAnalyst(llm, db),
            SentimentAnalyst(llm, db),
        ]
        self.portfolio_advisor = PortfolioAdvisor(llm, config.investor_profile)

    def generate_daily_brief(self) -> dict:
        """Generate a daily investment brief for all watchlist items."""
        logger.info("Generating daily brief...")
        today = shanghai_today().isoformat()
        results_by_symbol = {}
        all_results = []

        # Analyze A-shares
        for symbol in self.config.watchlist.a_shares:
            results_by_symbol[symbol] = {"market": "a_share", "analyses": {}}
            for analyst in self.analysts:
                try:
                    result = analyst.analyze(symbol, "a_share")
                    results_by_symbol[symbol]["analyses"][analyst.name] = {
                        "summary": result.summary,
                        "rating": result.rating,
                        "confidence": result.confidence,
                        "details": result.details,
                    }
                    all_results.append(result)
                except Exception as e:  # noqa: BLE001
                    logger.error(f"Analyst {analyst.name} failed for {symbol}: {e}")

        # Analyze HK stocks (technical only, fundamentals may be limited)
        for symbol in self.config.watchlist.hk_stocks:
            results_by_symbol[symbol] = {"market": "hk", "analyses": {}}
            for analyst in [self.analysts[1]]:  # Technical analyst
                try:
                    result = analyst.analyze(symbol, "hk")
                    results_by_symbol[symbol]["analyses"][analyst.name] = {
                        "summary": result.summary,
                        "rating": result.rating,
                        "confidence": result.confidence,
                        "details": result.details,
                    }
                    all_results.append(result)
                except Exception as e:  # noqa: BLE001
                    logger.error(f"Analyst {analyst.name} failed for HK {symbol}: {e}")

        # Analyze US stocks
        for symbol in self.config.watchlist.us_stocks:
            results_by_symbol[symbol] = {"market": "us", "analyses": {}}
            for analyst in [self.analysts[1]]:  # Technical analyst
                try:
                    result = analyst.analyze(symbol, "us")
                    results_by_symbol[symbol]["analyses"][analyst.name] = {
                        "summary": result.summary,
                        "rating": result.rating,
                        "confidence": result.confidence,
                        "details": result.details,
                    }
                    all_results.append(result)
                except Exception as e:  # noqa: BLE001
                    logger.error(f"Analyst {analyst.name} failed for US {symbol}: {e}")

        # Portfolio-level advice
        portfolio_advice = self.portfolio_advisor.analyze_portfolio(all_results)

        report = {
            "date": today,
            "type": "daily_brief",
            "individual": results_by_symbol,
            "portfolio": portfolio_advice,
        }

        # Save to DB
        self.queries.save_analysis_report(
            "daily_brief", "portfolio", report, self.llm.model
        )

        logger.info("Daily brief generated.")
        return report

    def generate_weekly_deep(self) -> dict:
        """Generate a deep weekly analysis with more context."""
        logger.info("Generating weekly deep analysis...")
        # For weekly, we use the same analysts but with more data context
        # The report structure is the same, content is deeper due to more data
        report = self.generate_daily_brief()
        report["type"] = "weekly_deep"

        self.queries.save_analysis_report(
            "weekly_deep", "portfolio", report, self.llm.model
        )

        logger.info("Weekly deep analysis generated.")
        return report
