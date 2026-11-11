"""Portfolio advisor agent - holistic portfolio-level analysis."""

from __future__ import annotations

from loguru import logger

from src.analysis.base_analyst import AnalysisResult
from src.analysis.llm_client import LLMClient
from src.config import InvestorProfileConfig

SYSTEM_PROMPT = """你是一位专业的投资组合顾问。

输入分为两部分，请严格区分：
- **实际持仓**：用户当前真实持有的标的，附带份额、成本、最新价与浮动盈亏。
- **候选观察标的**：用户尚未买入、仅在观察池中的标的。

分析要求：
1. **持仓优先**：必须为每一个实际持仓给出明确操作建议，这是本次分析的核心。
2. **结合成本**：结论要参考该持仓的浮动盈亏与成本价，而不是只看行情走势。
3. **候选标的从简**：仅在确有配置价值时才提及，且不得挤占持仓建议。
4. **仓位测算**：结合投资者画像的可投资金与各币种合计市值给出比例建议。
5. **无持仓时**：若实际持仓为空，明确说明这一点，再从候选标的中给出建仓思路。

请用JSON格式返回：
{
    "summary": "一段话总结组合状况，需点明持仓整体盈亏情况",
    "risk_level": "低/中/高",
    "holdings_advice": [
        {
            "symbol": "代码",
            "market": "市场",
            "action": "持有/加仓/减仓/清仓/观望",
            "target_weight_pct": 0.0到100.0,
            "reason": "结合成本与浮动盈亏的理由"
        }
    ],
    "candidate_suggestions": [
        {"symbol": "代码", "market": "市场", "action": "建仓/观望", "reason": "理由"}
    ],
    "diversification_score": 0.0到1.0,
    "key_risks": ["组合风险1"],
    "monthly_investment_plan": "定投建议"
}"""

EMPTY_RESULT = {
    "summary": "无分析数据",
    "risk_level": "未知",
    "holdings_advice": [],
    "candidate_suggestions": [],
}


class PortfolioAdvisor:
    """Provides holistic portfolio advice based on individual analysis results."""

    name = "portfolio_advisor"

    def __init__(self, llm: LLMClient, profile: InvestorProfileConfig | None = None):
        self.llm = llm
        self.profile = profile or InvestorProfileConfig()

    def analyze_portfolio(
        self, individual_results: list[AnalysisResult], valuation: dict | None = None
    ) -> dict:
        """Synthesize individual analyses into portfolio-level advice.

        Analyses are split into held positions and watchlist candidates so the
        model is told which symbols the user actually owns. Matching is by
        symbol alone: a holding whose ``market`` was recorded incorrectly still
        pairs with its analysis.
        """
        if not individual_results:
            return dict(EMPTY_RESULT)

        holdings = (valuation or {}).get("holdings", [])
        held_symbols = {holding["symbol"] for holding in holdings}
        held_results = [r for r in individual_results if r.symbol in held_symbols]
        candidate_results = [r for r in individual_results if r.symbol not in held_symbols]

        sections = ["投资者画像：\n" + "\n".join(self._profile_lines())]
        if holdings:
            sections.append(self._holdings_section(valuation or {}))
        else:
            sections.append("实际持仓：\n当前没有登记任何持仓。")
        if held_results:
            sections.append(self._analysis_section("持仓标的分析结果：", held_results))
        elif holdings:
            sections.append(
                "持仓标的分析结果：\n持仓标的不在本次分析范围内，"
                "请提示用户将其加入 watchlist 后重新生成报告。"
            )
        if candidate_results:
            sections.append(self._analysis_section("候选观察标的分析结果：", candidate_results))

        try:
            return self.llm.chat_json(
                SYSTEM_PROMPT,
                "\n\n".join(sections),
                request_context=self.name,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"Portfolio analysis failed: {e}")
            return {"summary": f"组合分析失败: {e}", "risk_level": "未知"}

    def _profile_lines(self) -> list[str]:
        """Describe the investor profile, omitting unset optional inputs."""
        lines = [f"风险偏好: {self.profile.risk_preference}"]
        if self.profile.monthly_income is not None:
            lines.append(f"税前月收入: {self.profile.monthly_income:,.0f} 元")
        if self.profile.investable_cash is not None:
            lines.append(f"可投资现金: {self.profile.investable_cash:,.0f} 元")
        if self.profile.fund_assets is not None:
            lines.append(f"基金资产: {self.profile.fund_assets:,.0f} 元")
        return lines

    @staticmethod
    def _analysis_section(title: str, results: list[AnalysisResult]) -> str:
        """Format analyst output under a section heading."""
        lines = [
            f"[{result.symbol}] {result.analyst_name}: "
            f"评级={result.rating}, 置信度={result.confidence:.1f}, "
            f"摘要={result.summary}"
            for result in results
        ]
        return title + "\n" + "\n".join(lines)

    @staticmethod
    def _holdings_section(valuation: dict) -> str:
        """Describe each holding with the position detail needed for sizing advice."""
        lines = ["实际持仓："]
        for holding in valuation.get("holdings", []):
            head = (
                f"[{holding['symbol']}] {holding['market']} {holding['name']}: "
                f"份额={holding['shares']:.2f}, 成本价={holding['cost_price']:.4f}, "
                f"成本市值={holding['cost_value']:.2f} {holding['currency']}"
            )
            if holding["market_value"] is None:
                lines.append(f"{head}, 无最新本地价格数据，无法估值")
                continue
            pnl_pct = (
                f" ({holding['unrealized_pnl_pct']:.2f}%)"
                if holding["unrealized_pnl_pct"] is not None
                else " (成本基准不可用)"
            )
            lines.append(
                f"{head}, 最新价={holding['latest_price']:.4f} "
                f"(截至 {holding['price_date']}), "
                f"市值={holding['market_value']:.2f} {holding['currency']}, "
                f"浮盈亏={holding['unrealized_pnl']:.2f} {holding['currency']}{pnl_pct}"
            )

        for total in valuation.get("by_currency", []):
            pnl_pct = (
                f" ({total['unrealized_pnl_pct']:.2f}%)"
                if total.get("unrealized_pnl_pct") is not None
                else ""
            )
            lines.append(
                f"{total['currency']} 合计: 成本 {total['cost_value']:.2f}, "
                f"市值 {total['market_value']:.2f}, "
                f"浮盈亏 {total['unrealized_pnl']:.2f}{pnl_pct} "
                f"(已估值 {total['valued_count']} 个标的)"
            )

        unvalued = valuation.get("unvalued_count", 0)
        if unvalued:
            lines.append(f"另有 {unvalued} 个持仓缺少本地价格数据，未纳入合计。")
        return "\n".join(lines)
