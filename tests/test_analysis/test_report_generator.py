"""Tests for the report generator orchestration."""

from src.analysis.llm_client import LLMClient
from src.analysis.report_generator import ReportGenerator


def test_daily_brief_structure(test_db, sample_config, mock_llm):
    """Daily brief assembles per-symbol analyses plus portfolio advice."""
    llm = LLMClient(sample_config.llm)
    generator = ReportGenerator(llm, test_db, sample_config)
    report = generator.generate_daily_brief()

    assert report["type"] == "daily_brief"
    assert "600519" in report["individual"]
    assert "portfolio" in report
    # With an empty DB, analysts return low-confidence fallbacks without LLM calls,
    # and the portfolio advisor still synthesizes them via the mocked LLM.
    mock_llm.assert_called_once()


def test_weekly_deep_structure(test_db, sample_config, mock_llm):
    """Weekly deep report adds a recap section and persists to the DB."""
    llm = LLMClient(sample_config.llm)
    generator = ReportGenerator(llm, test_db, sample_config)
    report = generator.generate_weekly_deep()

    assert report["type"] == "weekly_deep"
    assert "600519" in report["individual"]
    assert "portfolio" in report
    assert "weekly_recap" in report  # None when no prior daily briefs exist
    assert report["weekly_recap"] is None


def test_weekly_recap_uses_past_briefs(test_db, sample_config, mock_llm):
    """Weekly recap summarizes previously saved daily briefs."""
    from src.storage.queries import QueryService

    queries = QueryService(test_db)
    queries.save_analysis_report(
        "daily_brief",
        "portfolio",
        {"date": "2026-10-21", "type": "daily_brief", "portfolio": {"summary": "昨日摘要"}},
        "test-model",
    )

    llm = LLMClient(sample_config.llm)
    generator = ReportGenerator(llm, test_db, sample_config)
    report = generator.generate_weekly_deep()

    # Recap calls the (mocked) LLM once for the portfolio advice and once for the recap
    assert report["weekly_recap"] is not None
    assert report["weekly_recap"]["summary"] == "测试分析"
