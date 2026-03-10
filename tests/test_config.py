"""Tests for configuration loading."""

from src.config import AppConfig, WatchlistConfig, LLMConfig


def test_default_config():
    """Test that AppConfig can be created with defaults."""
    config = AppConfig()
    assert config.log_level == "INFO"
    assert config.database.path == "data/investment.db"
    assert config.llm.provider == "openai"


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
