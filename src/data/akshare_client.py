"""Small, normalized adapter around the AKShare data APIs."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any

import pandas as pd
from loguru import logger

from src.utils.chinese_calendar import shanghai_today
from src.utils.rate_limiter import RateLimiter


class BeijingExchangeUnsupportedError(RuntimeError):
    """Raised when a Beijing Stock Exchange symbol has no reachable provider.

    Eastmoney is the only source that serves this board, so when its circuit
    breaker is open the fallback chain cannot substitute for it.
    """


class AkshareDataClient:
    """Fetch market data from AKShare and normalize its column names."""

    _PROXY_ENVIRONMENT_VARIABLES = (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "SOCKS_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "socks_proxy",
    )

    _PROXY_BYPASS_VARIABLES = ("NO_PROXY", "no_proxy")

    # Beijing Stock Exchange code ranges. Only Eastmoney serves this board;
    # Sina and Tencent return empty payloads for every prefix spelling.
    _BSE_PREFIXES = ("43", "83", "87", "88", "92")

    def __init__(
        self,
        api: Any | None = None,
        rate_limiter: RateLimiter | None = None,
        use_env_proxy: bool = False,
        max_retries: int = 2,
        retry_delay_seconds: float = 2.0,
    ):
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
        self.use_env_proxy = use_env_proxy
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self._eastmoney_kline_available = True

    def fetch_a_share_quotes(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Fetch forward-adjusted A-share daily quotes with provider fallback."""
        if self._eastmoney_kline_available:
            try:
                raw = self._call(
                    "a_share_quotes_eastmoney",
                    self.api.stock_zh_a_hist,
                    symbol=symbol,
                    period="daily",
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust="qfq",
                    retries=0,
                )
            except Exception as error:  # noqa: BLE001
                if self._is_connectivity_error(error):
                    self._eastmoney_kline_available = False
                logger.warning(
                    f"Eastmoney A-share quotes failed for {symbol} ({error}); "
                    "falling back to Sina."
                )
                raw = self._fetch_a_share_quotes_fallback(symbol, start, end)
        else:
            raw = self._fetch_a_share_quotes_fallback(symbol, start, end)
        return self._normalize_quotes(raw)

    def _fetch_a_share_quotes_fallback(
        self, symbol: str, start: date, end: date
    ) -> pd.DataFrame:
        """Fetch A-share quotes from Sina, then Tencent if Sina is unavailable."""
        if self._is_bse(symbol):
            raise BeijingExchangeUnsupportedError(
                f"{symbol} is listed on the Beijing Stock Exchange, which only "
                "Eastmoney serves; Sina and Tencent have no data for it."
            )
        provider_symbol = self._a_share_provider_symbol(symbol)
        try:
            return self._call(
                "a_share_quotes_sina",
                self.api.stock_zh_a_daily,
                symbol=provider_symbol,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="qfq",
            )
        except Exception as error:  # noqa: BLE001
            logger.warning(
                f"Sina A-share quotes failed for {symbol} ({error}); "
                "falling back to Tencent."
            )
            return self._call(
                "a_share_quotes_tencent",
                self.api.stock_zh_a_hist_tx,
                symbol=provider_symbol,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="qfq",
            )

    def fetch_hk_quotes(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Fetch Hong Kong stock daily quotes with an alternate source fallback."""
        if self._eastmoney_kline_available:
            try:
                raw = self._call(
                    "hk_quotes_eastmoney",
                    self.api.stock_hk_hist,
                    symbol=symbol,
                    period="daily",
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust="qfq",
                    retries=0,
                )
            except Exception as error:  # noqa: BLE001
                if self._is_connectivity_error(error):
                    self._eastmoney_kline_available = False
                logger.warning(
                    f"Eastmoney HK quotes failed for {symbol} ({error}); "
                    "falling back to Sina."
                )
                raw = self._fetch_hk_quotes_fallback(symbol)
        else:
            raw = self._fetch_hk_quotes_fallback(symbol)
        quotes = self._normalize_quotes(raw)
        return quotes[(quotes["date"] >= start) & (quotes["date"] <= end)]

    def fetch_us_quotes(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Fetch U.S. stock daily quotes with an alternate source fallback.

        AKShare expects its U.S. market identifier (for example ``105.AAPL``),
        rather than necessarily the display ticker alone.
        """
        if self._eastmoney_kline_available:
            try:
                raw = self._call(
                    "us_quotes_eastmoney",
                    self.api.stock_us_hist,
                    symbol=symbol,
                    period="daily",
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust="qfq",
                    retries=0,
                )
            except Exception as error:  # noqa: BLE001
                if self._is_connectivity_error(error):
                    self._eastmoney_kline_available = False
                logger.warning(
                    f"Eastmoney U.S. quotes failed for {symbol} ({error}); "
                    "falling back to Sina."
                )
                raw = self._fetch_us_quotes_fallback(symbol)
        else:
            raw = self._fetch_us_quotes_fallback(symbol)
        quotes = self._normalize_quotes(raw)
        return quotes[(quotes["date"] >= start) & (quotes["date"] <= end)]

    def _fetch_hk_quotes_fallback(self, symbol: str) -> pd.DataFrame:
        """Fetch Hong Kong history from Sina."""
        return self._call(
            "hk_quotes_sina",
            self.api.stock_hk_daily,
            symbol=symbol,
            adjust="",
        )

    def _fetch_us_quotes_fallback(self, symbol: str) -> pd.DataFrame:
        """Fetch U.S. history from Sina."""
        return self._call(
            "us_quotes_sina",
            self.api.stock_us_daily,
            symbol=symbol,
            adjust="",
        )

    def fetch_fund_nav(self, fund_code: str, start: date, end: date) -> pd.DataFrame:
        """Fetch open-fund or ETF net-asset-value history."""
        if self._is_etf(fund_code):
            if self._eastmoney_kline_available:
                try:
                    raw = self._call(
                        "etf_nav_eastmoney",
                        self.api.fund_etf_hist_em,
                        symbol=fund_code,
                        period="daily",
                        start_date=start.strftime("%Y%m%d"),
                        end_date=end.strftime("%Y%m%d"),
                        adjust="qfq",
                        retries=0,
                    )
                except Exception as error:  # noqa: BLE001
                    if self._is_connectivity_error(error):
                        self._eastmoney_kline_available = False
                    logger.warning(
                        f"Eastmoney ETF quotes failed for {fund_code} ({error}); "
                        "falling back to Sina."
                    )
                    raw = self._fetch_etf_nav_fallback(fund_code)
            else:
                raw = self._fetch_etf_nav_fallback(fund_code)
            quotes = self._normalize_quotes(raw)
            quotes = quotes[(quotes["date"] >= start) & (quotes["date"] <= end)]
            return pd.DataFrame(
                {
                    "date": quotes["date"],
                    "nav": quotes["close"],
                    "acc_nav": None,
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
        if not self._eastmoney_kline_available:
            return pd.DataFrame(
                columns=["date", "main_net_inflow", "small_net_inflow", "total_net_inflow"]
            )

        market = self._fund_flow_market(symbol)
        try:
            raw = self._call(
                "fund_flow",
                self.api.stock_individual_fund_flow,
                stock=symbol,
                market=market,
            )
        except Exception as error:
            if self._is_connectivity_error(error):
                self._eastmoney_kline_available = False
            raise
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

    def _call(
        self, key: str, method: Any, retries: int | None = None, **kwargs: Any
    ) -> pd.DataFrame:
        retry_limit = self.max_retries if retries is None else retries
        for attempt in range(retry_limit + 1):
            self.rate_limiter.wait(key)
            try:
                with self._request_environment():
                    result = method(**kwargs)
            except Exception as error:
                if attempt == retry_limit:
                    raise
                delay = self.retry_delay_seconds * (2**attempt)
                logger.warning(
                    f"AKShare {key} request failed ({error}); "
                    f"retrying in {delay:.1f}s ({attempt + 1}/{retry_limit})"
                )
                time.sleep(delay)
                continue

            if not isinstance(result, pd.DataFrame):
                raise TypeError(
                    f"AKShare {key} returned {type(result).__name__}, expected DataFrame"
                )
            return result

        raise RuntimeError(f"AKShare {key} request exhausted without a result")

    @contextmanager
    def _request_environment(self) -> Iterator[None]:
        """Optionally prevent requests inside AKShare from inheriting shell proxies.

        Clearing the proxy variables alone is not enough: with none of them set,
        ``urllib`` falls back to the operating system's proxy configuration, so
        macOS system proxies still apply. Setting ``NO_PROXY=*`` both satisfies
        the environment lookup and instructs requests to bypass every host, which
        makes ``use_env_proxy=False`` mean a genuinely direct connection.
        """
        if self.use_env_proxy:
            yield
            return

        saved = {
            name: os.environ.pop(name)
            for name in self._PROXY_ENVIRONMENT_VARIABLES + self._PROXY_BYPASS_VARIABLES
            if name in os.environ
        }
        os.environ["NO_PROXY"] = "*"
        try:
            yield
        finally:
            for name in self._PROXY_BYPASS_VARIABLES:
                os.environ.pop(name, None)
            os.environ.update(saved)

    def _fetch_etf_nav_fallback(self, fund_code: str) -> pd.DataFrame:
        """Fetch exchange-traded fund history from Sina."""
        return self._call(
            "etf_nav_sina",
            self.api.fund_etf_hist_sina,
            symbol=self._fund_provider_symbol(fund_code),
        )

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
                "turnover": cls._numeric(cls._column(raw, ["成交额", "turnover", "amount"])),
                "change_pct": cls._numeric(cls._column(raw, ["涨跌幅", "change_pct"])),
            }
        ).dropna(subset=["date", "close"]).sort_values("date")
        calculated_change = (normalized["close"].pct_change() * 100).round(4)
        normalized["change_pct"] = normalized["change_pct"].fillna(calculated_change)
        return normalized

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
        return fund_code.startswith(("15", "16", "50", "51", "52", "56", "58", "59"))

    @classmethod
    def _fund_flow_market(cls, symbol: str) -> str:
        """Return Eastmoney's money-flow market identifier for a symbol."""
        if cls._is_bse(symbol):
            return "bj"
        return "sh" if symbol.startswith("6") else "sz"

    @classmethod
    def _is_bse(cls, symbol: str) -> bool:
        """Identify Beijing Stock Exchange listings, including the 92xxxx range."""
        return symbol.startswith(cls._BSE_PREFIXES)

    @classmethod
    def _a_share_provider_symbol(cls, symbol: str) -> str:
        """Convert a six-digit A-share code to Sina/Tencent's market prefix.

        Beijing Stock Exchange codes are checked first: 92xxxx would otherwise
        match the Shanghai ``9`` prefix used by B-shares.
        """
        if cls._is_bse(symbol):
            return f"bj{symbol}"
        prefix = "sh" if symbol.startswith(("5", "6", "9")) else "sz"
        return f"{prefix}{symbol}"

    @staticmethod
    def _fund_provider_symbol(symbol: str) -> str:
        """Convert an exchange-traded fund code to Sina's market prefix."""
        prefix = "sh" if symbol.startswith("5") else "sz"
        return f"{prefix}{symbol}"

    @staticmethod
    def _is_connectivity_error(error: Exception) -> bool:
        """Identify provider or proxy failures appropriate for a sync-run circuit breaker."""
        return isinstance(error, (ConnectionError, OSError, TimeoutError)) or type(error).__name__ in {
            "ConnectTimeout",
            "ConnectionError",
            "ProxyError",
            "ReadTimeout",
        }

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