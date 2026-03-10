"""Base analyst agent interface and result data class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AnalysisResult:
    """Structured result from an analyst agent."""

    analyst_name: str
    symbol: str
    summary: str
    rating: str  # bullish, neutral, bearish
    confidence: float  # 0.0 to 1.0
    details: dict = field(default_factory=dict)
    raw_llm_response: str = ""


class BaseAnalyst(ABC):
    """Base class for all analyst agents."""

    def __init__(self, llm, db):
        self.llm = llm
        self.db = db

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def analyze(self, symbol: str, market: str = "a_share") -> AnalysisResult:
        ...
