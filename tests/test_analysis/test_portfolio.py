"""Tests for the portfolio advisor agent."""

from src.analysis.base_analyst import AnalysisResult
from src.analysis.llm_client import LLMClient
from src.analysis.portfolio import PortfolioAdvisor
from src.config import LLMConfig, ProfileConfig


def _make_advisor(profile: ProfileConfig | None = None) -> PortfolioAdvisor:
    llm = LLMClient(LLMConfig(model="test-model", api_key="k", base_url="https://x"))
    return PortfolioAdvisor(llm, profile)


def _sample_result() -> AnalysisResult:
    return AnalysisResult(
        analyst_name="technical",
        symbol="600519",
        summary="走势强势",
        rating="bullish",
        confidence=0.8,
    )


def test_profile_injected_into_prompt(mock_llm):
    """Profile config should appear in the system prompt sent to the LLM."""
    profile = ProfileConfig(
        monthly_income=50000, available_cash=100000, fund_assets=800000, risk_preference="高"
    )
    advisor = _make_advisor(profile)
    advisor.analyze_portfolio([_sample_result()])

    payload = mock_llm.call_args.kwargs["json"]
    assert "5.0万" in payload["system"]  # monthly_income formatted as 万元
    assert "高" in payload["system"]  # risk preference
    assert "600519" in payload["messages"][0]["content"]


def test_holdings_included_in_message(mock_llm):
    """Holdings should be included in the user message when provided."""
    advisor = _make_advisor()
    holdings = [
        {"market": "a_share", "symbol": "600519", "name": "贵州茅台", "shares": 100, "cost_price": 1500.0}
    ]
    advisor.analyze_portfolio([_sample_result()], holdings=holdings)

    payload = mock_llm.call_args.kwargs["json"]
    user_msg = payload["messages"][0]["content"]
    assert "贵州茅台" in user_msg
    assert "1500" in user_msg


def test_empty_results_returns_fallback(mock_llm):
    """No individual results -> fallback advice without calling the LLM."""
    advisor = _make_advisor()
    result = advisor.analyze_portfolio([])
    assert result["summary"] == "无分析数据"
    mock_llm.assert_not_called()
