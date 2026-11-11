"""News sentiment analysis agent."""

from __future__ import annotations

import json

from loguru import logger

from src.analysis.base_analyst import AnalysisResult, BaseAnalyst
from src.analysis.llm_client import LLMClient
from src.storage.database import Database
from src.storage.queries import QueryService

SYSTEM_PROMPT = """你是一位专业的市场舆情分析师。根据提供的相关新闻，分析市场情绪和舆论导向。

请从以下维度分析：
1. **整体舆情**：正面/中性/负面
2. **关键事件**：影响股价的重大新闻
3. **市场情绪**：投资者情绪倾向
4. **风险提示**：舆情中暗含的风险信号

请用JSON格式返回：
{
    "summary": "一段话总结舆情状况",
    "rating": "bullish 或 neutral 或 bearish",
    "confidence": 0.0到1.0,
    "key_events": ["关键事件1", "关键事件2"],
    "sentiment_score": -1.0到1.0（负面到正面）,
    "risk_signals": ["风险信号1"],
    "opportunity_signals": ["机会信号1"]
}"""


class SentimentAnalyst(BaseAnalyst):
    """Analyzes news sentiment for stocks."""

    name = "sentiment"

    def __init__(self, llm: LLMClient, db: Database):
        super().__init__(llm, db)
        self.queries = QueryService(db)

    def analyze(
        self, symbol: str, market: str = "a_share", news_days: int = 7
    ) -> AnalysisResult:
        news_items = self.queries.get_recent_news(symbol, days=news_days)

        if not news_items:
            return AnalysisResult(
                analyst_name=self.name,
                symbol=symbol,
                summary=f"近{news_days}天无相关新闻",
                rating="neutral",
                confidence=0.3,
            )

        # Format news for LLM
        news_text = "\n\n".join(
            f"标题: {item['title']}\n内容: {item['content'][:500]}"
            for item in news_items[:20]  # Limit to 20 most recent
        )

        user_message = f"请分析股票 {symbol} 的近期舆情：\n\n{news_text}"

        try:
            result = self.llm.chat_json(
                SYSTEM_PROMPT,
                user_message,
                request_context=f"{self.name}:{market}/{symbol}",
            )
            return AnalysisResult(
                analyst_name=self.name,
                symbol=symbol,
                summary=result.get("summary", "舆情分析完成"),
                rating=result.get("rating", "neutral"),
                confidence=float(result.get("confidence", 0.5)),
                details=result,
                raw_llm_response=json.dumps(result, ensure_ascii=False),
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"Sentiment analysis failed for {symbol}: {e}")
            return AnalysisResult(
                analyst_name=self.name,
                symbol=symbol,
                summary=f"舆情分析失败: {e}",
                rating="neutral",
                confidence=0.0,
            )
