"""Small, normalized adapter around the AKShare data APIs."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from src.utils.chinese_calendar import shanghai_today
from src.utils.rate_limiter import RateLimiter


class AkshareDataClient:
    """Fetch market data from AKShare and normalize its column names."""

    def __init__(self, api: Any | None = None, rate_limiter: RateLimiter | None = None):
        if api is None:
            try:
                import akshare as api
            except ImportError as error:
                raise RuntimeError(
                    "AKShare is required for data synchronization. "
                    "Install the project dependencies before running sync."
                ) from error

        self.api = api
        self.rate_limiter = rate_limiter or RateLimiter(calls_per_second=1.0)

    def fetch_a_share_quotes(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Fetch forward-adjusted A-share daily quotes."""
        raw = self._call(
            "a_share_quotes",
            self.api.stock_zh_a_hist,
            symbol=symbol,
            period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="qfq",
        )
        return self._normalize_quotes(raw)

    def fetch_hk_quotes(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Fetch forward-adjusted Hong Kong stock daily quotes."""
        raw = self._call(
            "hk_quotes",
            self.api.stock_hk_hist,
            symbol=symbol,
            period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="qfq",
        )
        return self._normalize_quotes(raw)

    def fetch_us_quotes(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Fetch forward-adjusted U.S. stock daily quotes.

        AKShare expects its U.S. market identifier (for example ``105.AAPL``),
        rather than necessarily the display ticker alone.
        """
        raw = self._call(
            "us_quotes",
            self.api.stock_us_hist,
            symbol=symbol,
            period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="qfq",
        )
        return self._normalize_quotes(raw)

    def fetch_fund_nav(self, fund_code: str, start: date, end: date) -> pd.DataFrame:
        """Fetch open-fund or ETF net-asset-value history."""
        if self._is_etf(fund_code):
            raw = self._call(
                "etf_nav",
                self.api.fund_etf_hist_em,
                symbol=fund_code,
                period="daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="qfq",
            )
            quotes = self._normalize_quotes(raw)
            return pd.DataFrame(
                {
                    "date": quotes["date"],
                    "nav": quotes["close"],
                    "acc_nav": pd.NA,
                    "daily_return": quotes["change_pct"],
                }
            )

        raw = self._call(
            "open_fund_nav",
            self.api.fund_open_fund_info_em,
            symbol=fund_code,
            indicator="单位净值走势",
        )
        return self._normalize_fund_nav(raw, start, end)

    def fetch_fund_flow(self, symbol: str) -> pd.DataFrame:
        """Fetch A-share individual-stock money-flow history."""
        market = "sh" if symbol.startswith("6") else "sz"
        raw = self._call(
            "fund_flow",
            self.api.stock_individual_fund_flow,
            stock=symbol,
            market=market,
        )
        return self._normalize_fund_flow(raw)

    def fetch_latest_financial_indicators(self, symbol: str) -> tuple[date, dict] | None:
        """Fetch the latest financial-indicator row as a serializable dictionary."""
        raw = self._call(
            "financial_indicators",
            self.api.stock_financial_analysis_indicator,
            symbol=symbol,
            start_year=str(shanghai_today().year - 5),
        )
        if raw.empty:
            return None

        date_column = self._find_column(raw, ["日期", "报告期", "报告日期", "截止日期", "date"])
        if date_column is None:
            return None

        rows = raw.copy()
        rows["_report_date"] = pd.to_datetime(rows[date_column], errors="coerce")
        rows = rows.dropna(subset=["_report_date"]).sort_values("_report_date")
        if rows.empty:
            return None

        latest = rows.iloc[-1]
        report_date = latest["_report_date"].date()
        data = {
            column: self._to_scalar(value)
            for column, value in latest.drop(labels=["_report_date"]).items()
        }
        return report_date, data

    def fetch_news(self, symbol: str) -> pd.DataFrame:
        """Fetch recent company news in the application's common shape."""
        raw = self._call("stock_news", self.api.stock_news_em, symbol=symbol)
        if raw.empty:
            return pd.DataFrame(columns=["title", "content", "url", "published_at"])

        return pd.DataFrame(
            {
                "title": self._column(raw, ["新闻标题", "标题", "title"]),
                "content": self._column(raw, ["新闻内容", "内容", "content"]),
                "url": self._column(raw, ["新闻链接", "链接", "url"]),
                "published_at": self._column(raw, ["发布时间", "日期", "published_at"]),
            }
        ).dropna(subset=["title"])

    def _call(self, key: str, method: Any, **kwargs: Any) -> pd.DataFrame:
        self.rate_limiter.wait(key)
        result = method(**kwargs)
        if not isinstance(result, pd.DataFrame):
            raise TypeError(f"AKShare {key} returned {type(result).__name__}, expected DataFrame")
        return result

    @classmethod
    def _normalize_quotes(cls, raw: pd.DataFrame) -> pd.DataFrame:
        """Map AKShare quote fields to the stock_quotes schema."""
        if raw.empty:
            return pd.DataFrame(
                columns=["date", "open", "high", "low", "close", "volume", "turnover", "change_pct"]
            )

        normalized = pd.DataFrame(
            {
                "date": pd.to_datetime(cls._column(raw, ["日期", "date"]), errors="coerce").dt.date,
                "open": cls._numeric(cls._column(raw, ["开盘", "open"])),
                "high": cls._numeric(cls._column(raw, ["最高", "high"])),
                "low": cls._numeric(cls._column(raw, ["最低", "low"])),
                "close": cls._numeric(cls._column(raw, ["收盘", "close"])),
                "volume": cls._numeric(cls._column(raw, ["成交量", "volume"])),
                "turnover": cls._numeric(cls._column(raw, ["成交额", "turnover"])),
                "change_pct": cls._numeric(cls._column(raw, ["涨跌幅", "change_pct"])),
            }
        )
        return normalized.dropna(subset=["date", "close"]).sort_values("date")

    @classmethod
    def _normalize_fund_nav(cls, raw: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
        if raw.empty:
            return pd.DataFrame(columns=["date", "nav", "acc_nav", "daily_return"])

        normalized = pd.DataFrame(
            {
                "date": pd.to_datetime(
                    cls._column(raw, ["净值日期", "日期", "date"]), errors="coerce"
                ).dt.date,
                "nav": cls._numeric(cls._column(raw, ["单位净值", "净值", "nav"])),
                "acc_nav": cls._numeric(cls._column(raw, ["累计净值", "acc_nav"])),
                "daily_return": cls._numeric(cls._column(raw, ["日增长率", "涨跌幅", "daily_return"])),
            }
        ).dropna(subset=["date", "nav"])
        return normalized[(normalized["date"] >= start) & (normalized["date"] <= end)].sort_values("date")

    @classmethod
    def _normalize_fund_flow(cls, raw: pd.DataFrame) -> pd.DataFrame:
        if raw.empty:
            return pd.DataFrame(
                columns=["date", "main_net_inflow", "small_net_inflow", "total_net_inflow"]
            )

        return pd.DataFrame(
            {
                "date": pd.to_datetime(cls._column(raw, ["日期", "date"]), errors="coerce").dt.date,
                "main_net_inflow": cls._numeric(
                    cls._column(raw, ["主力净流入-净额", "主力净流入", "main_net_inflow"])
                ),
                "small_net_inflow": cls._numeric(
                    cls._column(raw, ["小单净流入-净额", "小单净流入", "small_net_inflow"])
                ),
                "total_net_inflow": cls._numeric(
                    cls._column(raw, ["净流入", "总净流入", "total_net_inflow"])
                ),
            }
        ).dropna(subset=["date"])

    @staticmethod
    def _is_etf(fund_code: str) -> bool:
        return fund_code.startswith(("15", "16", "51", "52", "56", "58", "59"))

    @staticmethod
    def _find_column(frame: pd.DataFrame, candidates: list[str]) -> str | None:
        exact = {str(column): column for column in frame.columns}
        for candidate in candidates:
            if candidate in exact:
                return exact[candidate]

        normalized = {str(column).strip().lower(): column for column in frame.columns}
        for candidate in candidates:
            column = normalized.get(candidate.strip().lower())
            if column is not None:
                return column
        return None

    @classmethod
    def _column(cls, frame: pd.DataFrame, candidates: list[str]) -> pd.Series:
        column = cls._find_column(frame, candidates)
        if column is None:
            return pd.Series(pd.NA, index=frame.index, dtype="object")
        return frame[column]

    @staticmethod
    def _numeric(values: pd.Series) -> pd.Series:
        cleaned = values.astype(str).str.replace(",", "", regex=False).str.rstrip("%")
        return pd.to_numeric(cleaned, errors="coerce")

    @staticmethod
    def _to_scalar(value: Any) -> Any:
        if pd.isna(value):
            return None
        if isinstance(value, pd.Timestamp):
            return value.date().isoformat()
        return value.item() if hasattr(value, "item") else value