"""Tests for daily and weekly report orchestration."""

from src.analysis.base_analyst import AnalysisResult
from src.analysis.report_generator import WEEKLY_WINDOW, ReportGenerator


class FakeLLM:
    model = "test-model"


class RecordingAnalyst:
    """Captures the report window passed to an analyst."""

    def __init__(self, name):
        self.name = name
        self.calls = []

    def analyze(self, symbol, market, **kwargs):
        self.calls.append((symbol, market, kwargs))
        return AnalysisResult(self.name, symbol, "测试分析", "neutral", 0.5)


class FakePortfolioAdvisor:
    def analyze_portfolio(self, individual_results, valuation):
        return {"summary": "测试组合", "risk_level": "中", "allocation_suggestions": []}


def test_weekly_report_uses_independent_long_horizon_windows(sample_config, test_db):
    """Weekly generation dispatches long-horizon parameters without calling daily."""
    generator = ReportGenerator(FakeLLM(), test_db, sample_config)
    fundamental = RecordingAnalyst("fundamental")
    technical = RecordingAnalyst("technical")
    sentiment = RecordingAnalyst("sentiment")
    fund = RecordingAnalyst("fund")
    generator.analysts = [fundamental, technical, sentiment]
    generator.fund_analyst = fund
    generator.portfolio_advisor = FakePortfolioAdvisor()
    generator.generate_daily_brief = lambda: (_ for _ in ()).throw(AssertionError("daily called"))

    report = generator.generate_weekly_deep()

    assert report["type"] == "weekly_deep"
    assert report["analysis_window"] == {
        "fundamental_history_days": 730,
        "fundamental_recent_trading_days": 60,
        "technical_history_days": 365,
        "sentiment_days": 30,
        "fund_history_days": 365,
    }
    assert fundamental.calls[0][2] == {
        "history_days": WEEKLY_WINDOW.fundamental_history_days,
        "recent_trading_days": WEEKLY_WINDOW.fundamental_recent_trading_days,
    }
    assert technical.calls[0][2] == {"history_days": WEEKLY_WINDOW.technical_history_days}
    assert sentiment.calls[0][2] == {"news_days": WEEKLY_WINDOW.sentiment_days}
    assert fund.calls[0][2] == {"history_days": WEEKLY_WINDOW.fund_history_days}
    assert report["individual"]["510300"]["market"] == "fund"