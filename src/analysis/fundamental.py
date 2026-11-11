"""Fundamental analysis agent."""

from __future__ import annotations

import json
from datetime import timedelta

from loguru import logger

from src.analysis.base_analyst import AnalysisResult, BaseAnalyst
from src.analysis.llm_client import LLMClient
from src.storage.database import Database
from src.storage.queries import QueryService
from src.utils.chinese_calendar import shanghai_today

SYSTEM_PROMPT = """你是一位专业的股票基本面分析师。根据提供的财务数据和近期行情，分析公司的基本面状况。

请从以下维度分析：
1. **盈利能力**：ROE、净利润率、毛利率
2. **成长性**：营收增长、利润增长趋势
3. **财务健康**：资产负债率、现金流状况
4. **估值水平**：结合当前股价和财务数据评估

请用JSON格式返回分析结果：
{
    "summary": "一段话总结基本面状况",
    "rating": "bullish 或 neutral 或 bearish",
    "confidence": 0.0到1.0的置信度,
    "key_metrics": {"指标名": "评价"},
    "risks": ["风险点1", "风险点2"],
    "catalysts": ["潜在催化剂1", "催化剂2"]
}"""


class FundamentalAnalyst(BaseAnalyst):
    """Analyzes company fundamentals using financial report data."""

    name = "fundamental"

    def __init__(self, llm: LLMClient, db: Database):
        super().__init__(llm, db)
        self.queries = QueryService(db)

    def analyze(
        self,
        symbol: str,
        market: str = "a_share",
        history_days: int = 365,
        recent_trading_days: int = 20,
    ) -> AnalysisResult:
        # Gather data
        financials = self.queries.get_latest_financial_report(symbol)

        end = shanghai_today()
        start = end - timedelta(days=history_days)
        quotes = self.queries.get_quotes(market, symbol, start, end)

        # Build prompt with available data
        data_parts = []
        if financials:
            data_parts.append(f"财务指标数据:\n{json.dumps(financials, ensure_ascii=False, indent=2)}")
        if not quotes.empty:
            recent = quotes.tail(recent_trading_days)
            data_parts.append(
                f"近{len(recent)}个交易日行情:\n"
                f"最新价: {recent['close'].iloc[-1]}\n"
                f"区间最高: {recent['high'].max()}\n"
                f"区间最低: {recent['low'].min()}\n"
                f"区间涨跌幅: {((recent['close'].iloc[-1] / recent['close'].iloc[0]) - 1) * 100:.2f}%\n"
                f"区间日均成交额: {recent['turnover'].mean():,.0f}"
            )

        if not data_parts:
            return AnalysisResult(
                analyst_name=self.name,
                symbol=symbol,
                summary="数据不足，无法进行基本面分析",
                rating="neutral",
                confidence=0.0,
            )

        user_message = f"请分析股票 {symbol} 的基本面：\n\n" + "\n\n".join(data_parts)

        try:
            result = self.llm.chat_json(
                SYSTEM_PROMPT,
                user_message,
                request_context=f"{self.name}:{market}/{symbol}",
            )
            return AnalysisResult(
                analyst_name=self.name,
                symbol=symbol,
                summary=result.get("summary", "分析完成"),
                rating=result.get("rating", "neutral"),
                confidence=float(result.get("confidence", 0.5)),
                details=result,
                raw_llm_response=json.dumps(result, ensure_ascii=False),
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"Fundamental analysis failed for {symbol}: {e}")
            return AnalysisResult(
                analyst_name=self.name,
                symbol=symbol,
                summary=f"分析失败: {e}",
                rating="neutral",
                confidence=0.0,
            )
