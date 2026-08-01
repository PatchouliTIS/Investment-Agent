"""Tests for configuration loading."""

from src.config import AppConfig, LLMConfig, WatchlistConfig


def test_default_config():
    """Test that AppConfig can be created with defaults."""
    config = AppConfig()
    assert config.log_level == "INFO"
    assert config.database.path == "data/investment.db"
    assert config.llm.provider == "openai"
    assert config.akshare.use_env_proxy is False
    assert config.akshare.max_retries == 2
    assert config.investor_profile.monthly_income is None
    assert config.investor_profile.risk_preference == "未设置"


def test_watchlist_config():
    """Test watchlist config parsing."""
    wl = WatchlistConfig(
        a_shares=["600519", "000858"],
        funds=["510300"],
        hk_stocks=["00700"],
        us_stocks=["AAPL"],
    )
    assert len(wl.a_shares) == 2
    assert "600519" in wl.a_shares


def test_llm_config():
    """Test LLM config defaults."""
    llm = LLMConfig()
    assert llm.provider == "openai"
    assert llm.temperature == 0.3
    assert llm.max_tokens == 4096
