"""Technical analysis agent using pandas-computed indicators + LLM interpretation."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd
from loguru import logger

from src.analysis.base_analyst import AnalysisResult, BaseAnalyst
from src.analysis.llm_client import LLMClient
from src.storage.database import Database
from src.storage.queries import QueryService


SYSTEM_PROMPT = """你是一位专业的技术分析师。根据提供的技术指标数据，判断当前的技术面走势。

请从以下角度分析：
1. **趋势判断**：均线系统多头/空头排列，价格与均线的关系
2. **动量指标**：RSI超买超卖，MACD金叉死叉
3. **量价关系**：成交量与价格变动的配合
4. **支撑阻力**：关键价位

请用JSON格式返回：
{
    "summary": "一段话总结技术面",
    "rating": "bullish 或 neutral 或 bearish",
    "confidence": 0.0到1.0,
    "trend": "上升/震荡/下降",
    "support_level": 支撑位价格,
    "resistance_level": 阻力位价格,
    "signals": ["信号1", "信号2"],
    "suggestion": "短期操作建议"
}"""


class TechnicalAnalyst(BaseAnalyst):
    """Computes technical indicators locally, uses LLM for interpretation."""

    name = "technical"

    def __init__(self, llm: LLMClient, db: Database):
        super().__init__(llm, db)
        self.queries = QueryService(db)

    def analyze(self, symbol: str, market: str = "a_share") -> AnalysisResult:
        end = date.today()
        start = end - timedelta(days=300)  # ~1 year of trading days
        df = self.queries.get_quotes(market, symbol, start, end)

        if df.empty or len(df) < 20:
            return AnalysisResult(
                analyst_name=self.name,
                symbol=symbol,
                summary="行情数据不足，无法进行技术分析",
                rating="neutral",
                confidence=0.0,
            )

        indicators = self._compute_indicators(df)
        user_message = f"请对股票 {symbol} 进行技术分析：\n\n" + json.dumps(
            indicators, ensure_ascii=False, indent=2
        )

        try:
            result = self.llm.chat_json(SYSTEM_PROMPT, user_message)
            return AnalysisResult(
                analyst_name=self.name,
                symbol=symbol,
                summary=result.get("summary", "分析完成"),
                rating=result.get("rating", "neutral"),
                confidence=float(result.get("confidence", 0.5)),
                details=result,
                raw_llm_response=json.dumps(result, ensure_ascii=False),
            )
        except Exception as e:
            logger.error(f"Technical analysis failed for {symbol}: {e}")
            return AnalysisResult(
                analyst_name=self.name,
                symbol=symbol,
                summary=f"分析失败: {e}",
                rating="neutral",
                confidence=0.0,
            )

    def _compute_indicators(self, df: pd.DataFrame) -> dict:
        """Compute technical indicators using pure pandas."""
        close = df["close"]
        volume = df["volume"]

        indicators = {
            "current_price": float(close.iloc[-1]),
            "ma5": float(close.rolling(5).mean().iloc[-1]),
            "ma10": float(close.rolling(10).mean().iloc[-1]),
            "ma20": float(close.rolling(20).mean().iloc[-1]),
        }

        if len(df) >= 60:
            indicators["ma60"] = float(close.rolling(60).mean().iloc[-1])
        if len(df) >= 120:
            indicators["ma120"] = float(close.rolling(120).mean().iloc[-1])

        # RSI (14-period)
        indicators["rsi_14"] = float(self._compute_rsi(close, 14))

        # MACD
        macd, signal, hist = self._compute_macd(close)
        indicators["macd"] = float(macd)
        indicators["macd_signal"] = float(signal)
        indicators["macd_histogram"] = float(hist)

        # Volume ratio (today vs 20-day average)
        vol_ma20 = volume.rolling(20).mean().iloc[-1]
        if vol_ma20 > 0:
            indicators["volume_ratio"] = round(float(volume.iloc[-1] / vol_ma20), 2)

        # Recent performance
        if len(df) >= 5:
            indicators["5d_change_pct"] = round(
                float((close.iloc[-1] / close.iloc[-5] - 1) * 100), 2
            )
        if len(df) >= 20:
            indicators["20d_change_pct"] = round(
                float((close.iloc[-1] / close.iloc[-20] - 1) * 100), 2
            )

        # 52-week high/low (approx 250 trading days)
        lookback = min(len(df), 250)
        indicators["period_high"] = float(close.iloc[-lookback:].max())
        indicators["period_low"] = float(close.iloc[-lookback:].min())

        return indicators

    @staticmethod
    def _compute_rsi(series: pd.Series, period: int = 14) -> float:
        delta = series.diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1] if not rsi.empty else 50.0

    @staticmethod
    def _compute_macd(
        series: pd.Series, fast: int = 12, slow: int = 26, signal_period: int = 9
    ) -> tuple[float, float, float]:
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        signal = macd.ewm(span=signal_period, adjust=False).mean()
        histogram = macd - signal
        return macd.iloc[-1], signal.iloc[-1], histogram.iloc[-1]
