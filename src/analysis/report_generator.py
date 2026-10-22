"""Report generator - orchestrates all analyst agents."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from loguru import logger

from src.analysis.base_analyst import AnalysisResult
from src.analysis.fund import FundAnalyst
from src.analysis.fundamental import FundamentalAnalyst
from src.analysis.llm_client import LLMClient
from src.analysis.portfolio import PortfolioAdvisor
from src.analysis.sentiment import SentimentAnalyst
from src.analysis.technical import TechnicalAnalyst
from src.config import AppConfig
from src.storage.database import Database
from src.storage.queries import QueryService
from src.utils.chinese_calendar import shanghai_today


@dataclass(frozen=True)
class AnalysisWindow:
    """Data horizons used to keep daily and weekly analysis distinct."""

    fundamental_history_days: int
    fundamental_recent_trading_days: int
    technical_history_days: int
    sentiment_days: int
    fund_history_days: int


DAILY_WINDOW = AnalysisWindow(365, 20, 300, 7, 180)
WEEKLY_WINDOW = AnalysisWindow(730, 60, 365, 30, 365)


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
        self.fund_analyst = FundAnalyst(llm, db)
        self.portfolio_advisor = PortfolioAdvisor(llm, config.investor_profile)

    def generate_daily_brief(self) -> dict:
        """Generate the short-horizon daily investment brief."""
        return self._generate_report("daily_brief", DAILY_WINDOW)

    def generate_weekly_deep(self) -> dict:
        """Generate a long-horizon weekly report without reusing the daily path."""
        return self._generate_report("weekly_deep", WEEKLY_WINDOW)

    def _generate_report(self, report_type: str, window: AnalysisWindow) -> dict:
        logger.info(f"Generating {report_type} with analysis window {window}...")
        today = shanghai_today().isoformat()
        results_by_symbol = {}
        all_results = []

        for symbol in self.config.watchlist.a_shares:
            tasks = [
                (
                    self.analysts[0],
                    {
                        "history_days": window.fundamental_history_days,
                        "recent_trading_days": window.fundamental_recent_trading_days,
                    },
                ),
                (self.analysts[1], {"history_days": window.technical_history_days}),
                (self.analysts[2], {"news_days": window.sentiment_days}),
            ]
            self._analyze_symbol(results_by_symbol, all_results, symbol, "a_share", tasks)

        for symbol in self.config.watchlist.hk_stocks:
            self._analyze_symbol(
                results_by_symbol,
                all_results,
                symbol,
                "hk",
                [(self.analysts[1], {"history_days": window.technical_history_days})],
            )

        for symbol in self.config.watchlist.us_stocks:
            self._analyze_symbol(
                results_by_symbol,
                all_results,
                symbol,
                "us",
                [(self.analysts[1], {"history_days": window.technical_history_days})],
            )

        for symbol in self.config.watchlist.funds:
            self._analyze_symbol(
                results_by_symbol,
                all_results,
                symbol,
                "fund",
                [(self.fund_analyst, {"history_days": window.fund_history_days})],
            )

        valuation = self.queries.get_portfolio_valuation()
        portfolio_advice = self.portfolio_advisor.analyze_portfolio(all_results, valuation)

        report = {
            "date": today,
            "type": report_type,
            "analysis_window": asdict(window),
            "individual": results_by_symbol,
            "valuation": valuation,
            "portfolio": portfolio_advice,
        }

        self.queries.save_analysis_report(
            report_type, "portfolio", report, self.llm.model
        )

        logger.info(f"{report_type} generated.")
        return report

    @staticmethod
    def _result_payload(result: AnalysisResult) -> dict:
        return {
            "summary": result.summary,
            "rating": result.rating,
            "confidence": result.confidence,
            "details": result.details,
        }

    def _analyze_symbol(
        self,
        results_by_symbol: dict,
        all_results: list[AnalysisResult],
        symbol: str,
        market: str,
        tasks: list[tuple[object, dict]],
    ) -> None:
        results_by_symbol[symbol] = {"market": market, "analyses": {}}
        for analyst, kwargs in tasks:
            try:
                result = analyst.analyze(symbol, market, **kwargs)
                results_by_symbol[symbol]["analyses"][analyst.name] = self._result_payload(result)
                all_results.append(result)
            except Exception as error:  # noqa: BLE001
                logger.error(f"Analyst {analyst.name} failed for {market}/{symbol}: {error}")
