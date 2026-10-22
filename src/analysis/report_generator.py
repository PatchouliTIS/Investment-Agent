"""Report generator - orchestrates all analyst agents."""

from __future__ import annotations

from datetime import date

from loguru import logger

from src.analysis.base_analyst import AnalysisResult, BaseAnalyst
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

WEEKLY_RECAP_PROMPT = """你是一位专业的投资顾问。根据本周各交易日的投资日报摘要，回顾本周观点变化与组合动态。

请用JSON格式返回：
{
    "week_summary": "一段话总结本周",
    "key_changes": ["观点变化1", "观点变化2"],
    "next_week_focus": ["下周关注点1", "下周关注点2"]
}"""


class ReportGenerator:
    """Runs all analysts and assembles structured reports."""

    def __init__(self, llm: LLMClient, db: Database, config: AppConfig):
        self.llm = llm
        self.db = db
        self.config = config
        self.queries = QueryService(db)
        self.fundamental = FundamentalAnalyst(llm, db)
        self.technical = TechnicalAnalyst(llm, db)
        self.sentiment = SentimentAnalyst(llm, db)
        self.portfolio_advisor = PortfolioAdvisor(llm, config.profile)

    def generate_daily_brief(self) -> dict:
        """Generate a daily investment brief for all watchlist items."""
        logger.info("Generating daily brief...")
        results_by_symbol, all_results = self._collect_analyses(
            tech_lookback_days=300,
            fund_lookback_days=365,
            news_days=7,
        )
        portfolio_advice = self.portfolio_advisor.analyze_portfolio(
            all_results, holdings=self.queries.get_portfolio()
        )

        report = {
            "date": date.today().isoformat(),
            "type": "daily_brief",
            "individual": results_by_symbol,
            "valuation": valuation,
            "portfolio": portfolio_advice,
        }
        self.queries.save_analysis_report(
            report_type, "portfolio", report, self.llm.model
        )
        logger.info("Daily brief generated.")
        return report

    def generate_weekly_deep(self) -> dict:
        """Generate a deep weekly analysis with extended data windows and a weekly recap."""
        logger.info("Generating weekly deep analysis...")
        results_by_symbol, all_results = self._collect_analyses(
            tech_lookback_days=500,
            fund_lookback_days=730,
            news_days=30,
        )
        portfolio_advice = self.portfolio_advisor.analyze_portfolio(
            all_results, holdings=self.queries.get_portfolio()
        )

        report = {
            "date": date.today().isoformat(),
            "type": "weekly_deep",
            "individual": results_by_symbol,
            "portfolio": portfolio_advice,
            "weekly_recap": self._build_weekly_recap(),
        }
        self.queries.save_analysis_report(
            "weekly_deep", "portfolio", report, self.llm.model
        )
        logger.info("Weekly deep analysis generated.")
        return report

    def _collect_analyses(
        self,
        *,
        tech_lookback_days: int,
        fund_lookback_days: int,
        news_days: int,
    ) -> tuple[dict, list[AnalysisResult]]:
        """Run analysts across the whole watchlist.

        A-shares get fundamental + technical + sentiment analysis;
        HK/US stocks get technical analysis only (fundamental data unavailable).
        """
        results_by_symbol: dict = {}
        all_results: list[AnalysisResult] = []

        def run(analyst: BaseAnalyst, symbol: str, market: str, **kwargs):
            try:
                result = analyst.analyze(symbol, market, **kwargs)
            except Exception as e:
                logger.error(f"Analyst {analyst.name} failed for {market} {symbol}: {e}")
                return
            results_by_symbol[symbol]["analyses"][analyst.name] = {
                "summary": result.summary,
                "rating": result.rating,
                "confidence": result.confidence,
                "details": result.details,
            }
            all_results.append(result)

        for symbol in self.config.watchlist.a_shares:
            results_by_symbol[symbol] = {"market": "a_share", "analyses": {}}
            run(self.fundamental, symbol, "a_share", lookback_days=fund_lookback_days)
            run(self.technical, symbol, "a_share", lookback_days=tech_lookback_days)
            run(self.sentiment, symbol, "a_share", news_days=news_days)

        for symbol in self.config.watchlist.hk_stocks:
            results_by_symbol[symbol] = {"market": "hk", "analyses": {}}
            run(self.technical, symbol, "hk", lookback_days=tech_lookback_days)

        for symbol in self.config.watchlist.us_stocks:
            results_by_symbol[symbol] = {"market": "us", "analyses": {}}
            run(self.technical, symbol, "us", lookback_days=tech_lookback_days)

        return results_by_symbol, all_results

    def _build_weekly_recap(self) -> dict | None:
        """Summarize this week's daily briefs into a week-in-review via LLM."""
        past_reports = self.queries.get_recent_reports("daily_brief", limit=5)
        if not past_reports:
            logger.info("No daily briefs this week, skipping weekly recap.")
            return None

        lines = []
        for report in reversed(past_reports):  # chronological order
            portfolio_summary = report.get("portfolio", {}).get("summary", "无")
            lines.append(f"[{report.get('date')}] 组合建议: {portfolio_summary}")

        user_message = "以下是本周各交易日的日报组合建议摘要，请做周度回顾：\n\n" + "\n".join(lines)
        try:
            return self.llm.chat_json(WEEKLY_RECAP_PROMPT, user_message)
        except Exception as e:
            logger.error(f"Weekly recap generation failed: {e}")
            return None
