"""Fund analysis agent based on locally stored NAV history."""

from __future__ import annotations

import json
import math
from datetime import timedelta

import pandas as pd
from loguru import logger

from src.analysis.base_analyst import AnalysisResult, BaseAnalyst
from src.analysis.llm_client import LLMClient
from src.storage.database import Database
from src.storage.queries import QueryService
from src.utils.chinese_calendar import shanghai_today

SYSTEM_PROMPT = """你是一位专业的基金分析师。根据提供的基金净值、收益、回撤和波动率数据，分析基金表现。

请从以下维度分析：
1. **收益表现**：短中期收益及趋势
2. **回撤与波动**：最大回撤、年化波动率与风险特征
3. **持有建议**：结合风险收益特征给出持有、加仓、减仓或观望建议

请用JSON格式返回：
{
    "summary": "一段话总结基金表现",
    "rating": "bullish 或 neutral 或 bearish",
    "confidence": 0.0到1.0,
    "key_metrics": {"指标名": "数值或评价"},
    "risks": ["风险点1"],
    "catalysts": ["潜在催化剂1"],
    "suggestion": "操作建议"
}"""


class FundAnalyst(BaseAnalyst):
    """Analyzes fund performance using NAV-derived return and risk metrics."""

    name = "fund"

    def __init__(self, llm: LLMClient, db: Database):
        super().__init__(llm, db)
        self.queries = QueryService(db)

    def analyze(
        self,
        symbol: str,
        market: str = "fund",
        history_days: int = 365,
    ) -> AnalysisResult:
        end = shanghai_today()
        nav_history = self.queries.get_fund_nav(symbol, end - timedelta(days=history_days), end)
        if len(nav_history) < 2:
            return AnalysisResult(
                analyst_name=self.name,
                symbol=symbol,
                summary="基金净值数据不足，无法进行分析",
                rating="neutral",
                confidence=0.0,
            )

        metrics = self._compute_metrics(nav_history)
        user_message = (
            f"请分析基金 {symbol} 的净值表现。以下为本地计算的客观指标：\n\n"
            + json.dumps(metrics, ensure_ascii=False, indent=2)
        )
        try:
            result = self.llm.chat_json(
                SYSTEM_PROMPT,
                user_message,
                request_context=f"{self.name}:{market}/{symbol}",
            )
            key_metrics = {
                "最新净值": metrics["latest_nav"],
                "1日收益": self._format_pct(metrics["1d_return_pct"]),
                "5日收益": self._format_pct(metrics["5d_return_pct"]),
                "20日收益": self._format_pct(metrics["20d_return_pct"]),
                "60日收益": self._format_pct(metrics["60d_return_pct"]),
                "区间最大回撤": self._format_pct(metrics["max_drawdown_pct"]),
                "年化波动率": self._format_pct(metrics["annualized_volatility_pct"]),
            }
            key_metrics.update(result.get("key_metrics", {}))
            return AnalysisResult(
                analyst_name=self.name,
                symbol=symbol,
                summary=result.get("summary", "基金分析完成"),
                rating=result.get("rating", "neutral"),
                confidence=float(result.get("confidence", 0.5)),
                details={**metrics, **result, "key_metrics": key_metrics},
                raw_llm_response=json.dumps(result, ensure_ascii=False),
            )
        except Exception as error:  # noqa: BLE001
            logger.error(f"Fund analysis failed for {symbol}: {error}")
            return AnalysisResult(
                analyst_name=self.name,
                symbol=symbol,
                summary=f"分析失败: {error}",
                rating="neutral",
                confidence=0.0,
                details=metrics,
            )

    @staticmethod
    def _compute_metrics(nav_history: pd.DataFrame) -> dict:
        """Calculate return, drawdown, and volatility metrics from NAV data."""
        nav = pd.to_numeric(nav_history["nav"], errors="coerce").dropna().astype(float)
        daily_returns = nav.pct_change().dropna()
        cumulative_drawdown = nav.div(nav.cummax()).sub(1)

        return {
            "latest_nav": round(float(nav.iloc[-1]), 4),
            "history_days": len(nav),
            "1d_return_pct": FundAnalyst._period_return(nav, 1),
            "5d_return_pct": FundAnalyst._period_return(nav, 5),
            "20d_return_pct": FundAnalyst._period_return(nav, 20),
            "60d_return_pct": FundAnalyst._period_return(nav, 60),
            "period_return_pct": FundAnalyst._period_return(nav, len(nav) - 1),
            "max_drawdown_pct": round(float(cumulative_drawdown.min() * 100), 2),
            "annualized_volatility_pct": (
                round(float(daily_returns.std(ddof=1) * math.sqrt(252) * 100), 2)
                if len(daily_returns) > 1
                else 0.0
            ),
        }

    @staticmethod
    def _period_return(nav: pd.Series, periods: int) -> float | None:
        if periods <= 0 or len(nav) <= periods:
            return None
        return round(float((nav.iloc[-1] / nav.iloc[-periods - 1] - 1) * 100), 2)

    @staticmethod
    def _format_pct(value: float | None) -> str:
        return "数据不足" if value is None else f"{value:.2f}%"