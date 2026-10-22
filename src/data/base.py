"""Abstract base class for data fetchers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd


class DataFetcher(ABC):
    """Base interface for all market data fetchers."""

    @abstractmethod
    def fetch_quotes(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Fetch OHLCV price data for a symbol."""
        ...

    @abstractmethod
    def fetch_latest(self, symbols: list[str]) -> pd.DataFrame:
        """Fetch latest snapshot quotes for a list of symbols."""
        ...
