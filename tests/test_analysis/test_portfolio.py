"""Tests for the portfolio advisor prompt structure."""

from src.analysis.base_analyst import AnalysisResult
from src.analysis.portfolio import PortfolioAdvisor
from src.config import InvestorProfileConfig


class RecordingLLM:
    """Capture the prompt instead of contacting a provider."""

    def __init__(self):
        self.system_prompt = None
        self.user_message = None

    def chat_json(self, system_prompt, user_message, request_context="unspecified"):
        self.system_prompt = system_prompt
        self.user_message = user_message
        return {"summary": "ok", "holdings_advice": []}


def _result(symbol, name="fund"):
    return AnalysisResult(
        analyst_name=name, symbol=symbol, summary=f"{symbol} 摘要", rating="bullish", confidence=0.8
    )


def _valuation(market="fund"):
    return {
        "holdings": [
            {
                "market": market,
                "symbol": "159516",
                "name": "半导体设备ETF国泰",
                "shares": 5000.0,
                "cost_price": 0.831,
                "currency": "CNY",
                "latest_price": 0.65,
                "price_date": "2026-07-30",
                "cost_value": 4155.0,
                "market_value": 3250.0,
                "unrealized_pnl": -905.0,
                "unrealized_pnl_pct": -21.78,
            }
        ],
        "by_currency": [
            {
                "currency": "CNY",
                "market_value": 3250.0,
                "cost_value": 4155.0,
                "unrealized_pnl": -905.0,
                "unrealized_pnl_pct": -21.78,
                "valued_count": 1,
            }
        ],
        "unvalued_count": 0,
    }


def test_prompt_separates_holdings_from_candidates():
    """Held symbols and watchlist candidates land in distinct labelled sections."""
    llm = RecordingLLM()
    advisor = PortfolioAdvisor(llm, InvestorProfileConfig(investable_cash=100000))

    advisor.analyze_portfolio([_result("159516"), _result("510300")], _valuation())

    message = llm.user_message
    assert "实际持仓：" in message
    assert "持仓标的分析结果：" in message
    assert "候选观察标的分析结果：" in message
    # The held symbol's analysis must not appear under the candidate heading.
    candidates = message.split("候选观察标的分析结果：")[1]
    assert "510300" in candidates
    assert "159516" not in candidates


def test_prompt_carries_position_sizing_detail():
    """Shares, cost, latest price, and currency totals reach the model."""
    llm = RecordingLLM()
    advisor = PortfolioAdvisor(llm, InvestorProfileConfig())

    advisor.analyze_portfolio([_result("159516")], _valuation())

    message = llm.user_message
    assert "份额=5000.00" in message
    assert "成本价=0.8310" in message
    assert "最新价=0.6500" in message
    assert "-905.00" in message
    assert "-21.78%" in message
    assert "CNY 合计" in message


def test_holding_matches_analysis_despite_wrong_market():
    """Matching is by symbol, so a mis-recorded market still pairs correctly."""
    llm = RecordingLLM()
    advisor = PortfolioAdvisor(llm, InvestorProfileConfig())

    advisor.analyze_portfolio([_result("159516")], _valuation(market="a_share"))

    assert "持仓标的分析结果：" in llm.user_message
    assert "候选观察标的分析结果：" not in llm.user_message


def test_absent_holdings_are_stated_explicitly():
    """An empty portfolio is called out rather than silently omitted."""
    llm = RecordingLLM()
    advisor = PortfolioAdvisor(llm, InvestorProfileConfig())

    advisor.analyze_portfolio([_result("510300")], {"holdings": [], "by_currency": []})

    assert "当前没有登记任何持仓。" in llm.user_message


def test_unanalyzed_holding_is_flagged():
    """A holding outside the watchlist gets an explicit note, not silence."""
    llm = RecordingLLM()
    advisor = PortfolioAdvisor(llm, InvestorProfileConfig())

    advisor.analyze_portfolio([_result("510300")], _valuation())

    assert "持仓标的不在本次分析范围内" in llm.user_message


def test_no_results_returns_empty_advice_without_calling_llm():
    llm = RecordingLLM()
    advisor = PortfolioAdvisor(llm, InvestorProfileConfig())

    result = advisor.analyze_portfolio([], _valuation())

    assert llm.user_message is None
    assert result["holdings_advice"] == []
