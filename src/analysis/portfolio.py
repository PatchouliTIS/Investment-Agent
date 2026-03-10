"""Portfolio advisor agent - holistic portfolio-level analysis."""

from __future__ import annotations

import json

from loguru import logger

from src.analysis.base_analyst import AnalysisResult
from src.analysis.llm_client import LLMClient


SYSTEM_PROMPT = """你是一位专业的投资组合顾问。用户是一名程序员，月收入约4万元人民币（税前），
手头有约20万可支配资金和30万基金。

根据所有个股分析结果，给出组合层面的投资建议。

请从以下维度分析：
1. **仓位建议**：各标的的建议仓位比例
2. **风险评估**：组合整体风险水平
3. **多元化分析**：行业/市场分散度
4. **操作建议**：具体的调仓建议

请用JSON格式返回：
{
    "summary": "一段话总结组合状况",
    "risk_level": "低/中/高",
    "allocation_suggestions": [
        {"symbol": "代码", "market": "市场", "action": "持有/加仓/减仓/观望", "reason": "理由"}
    ],
    "diversification_score": 0.0到1.0,
    "key_risks": ["组合风险1"],
    "monthly_investment_plan": "定投建议（基于月收入4万）"
}"""


class PortfolioAdvisor:
    """Provides holistic portfolio advice based on individual analysis results."""

    name = "portfolio_advisor"

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def analyze_portfolio(self, individual_results: list[AnalysisResult]) -> dict:
        """Synthesize individual analyses into portfolio-level advice."""
        if not individual_results:
            return {
                "summary": "无分析数据",
                "risk_level": "未知",
                "allocation_suggestions": [],
            }

        # Build summary of all individual analyses
        summaries = []
        for result in individual_results:
            summaries.append(
                f"[{result.symbol}] {result.analyst_name}: "
                f"评级={result.rating}, 置信度={result.confidence:.1f}, "
                f"摘要={result.summary}"
            )

        user_message = (
            "以下是各个股的分析结果，请给出组合投资建议：\n\n"
            + "\n".join(summaries)
        )

        try:
            result = self.llm.chat_json(SYSTEM_PROMPT, user_message)
            return result
        except Exception as e:
            logger.error(f"Portfolio analysis failed: {e}")
            return {"summary": f"组合分析失败: {e}", "risk_level": "未知"}
