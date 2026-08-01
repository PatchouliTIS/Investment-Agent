"""Configuration management with Pydantic validation."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class WatchlistConfig(BaseModel):
    a_shares: list[str] = Field(default_factory=list)
    funds: list[str] = Field(default_factory=list)
    hk_stocks: list[str] = Field(default_factory=list)
    us_stocks: list[str] = Field(default_factory=list)


class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.3
    max_tokens: int = 4096
    output_format: Literal["json", "text"] = "json"
    text_response_max_chars: int = Field(default=300, ge=50, le=2000)
    max_retries: int = Field(default=2, ge=0, le=5)
    retry_delay_seconds: float = Field(default=2.0, ge=0.0)
    timeout_seconds: float = Field(default=90.0, gt=0.0, le=600.0)


class EmailConfig(BaseModel):
    smtp_host: str = "smtp.qq.com"
    smtp_port: int = 465
    use_ssl: bool = True
    sender: str = ""
    password: str = ""
    recipients: list[str] = Field(default_factory=list)


class ScheduleConfig(BaseModel):
    data_sync_cron: str = "0 18 * * 1-5"
    daily_report_cron: str = "30 19 * * 1-5"
    weekly_report_cron: str = "0 10 * * 6"
    alert_check_cron: str = "30 18 * * 1-5"


class AlertConfig(BaseModel):
    price_change_threshold: float = 5.0
    volume_spike_threshold: float = 3.0


class AkshareConfig(BaseModel):
    """Network behavior for AKShare market-data requests."""

    use_env_proxy: bool = False
    max_retries: int = Field(default=2, ge=0, le=5)
    retry_delay_seconds: float = Field(default=2.0, ge=0.0)


class InvestorProfileConfig(BaseModel):
    """Optional investor inputs used to tailor portfolio-level advice."""

    monthly_income: float | None = None
    investable_cash: float | None = None
    fund_assets: float | None = None
    risk_preference: str = "未设置"


class DatabaseConfig(BaseModel):
    path: str = "data/investment.db"


class AppConfig(BaseModel):
    watchlist: WatchlistConfig = WatchlistConfig()
    llm: LLMConfig = LLMConfig()
    llm_deep: LLMConfig | None = None
    email: EmailConfig = EmailConfig()
    schedule: ScheduleConfig = ScheduleConfig()
    alerts: AlertConfig = AlertConfig()
    akshare: AkshareConfig = AkshareConfig()
    investor_profile: InvestorProfileConfig = InvestorProfileConfig()
    database: DatabaseConfig = DatabaseConfig()
    log_level: str = "INFO"


_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def _resolve_env_vars(obj):
    """Recursively resolve ${ENV_VAR} patterns in config values."""
    if isinstance(obj, str):
        def replacer(match):
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))
        return _ENV_VAR_PATTERN.sub(replacer, obj)
    elif isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_env_vars(item) for item in obj]
    return obj


def load_config(path: str = "config/config.yaml") -> AppConfig:
    """Load and validate configuration from YAML file."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            f"Copy config/config.example.yaml to config/config.yaml and edit it."
        )

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    resolved = _resolve_env_vars(raw)
    return AppConfig(**resolved)
