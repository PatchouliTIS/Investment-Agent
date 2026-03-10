"""Shared test fixtures."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config import (
    AlertConfig,
    AppConfig,
    DatabaseConfig,
    EmailConfig,
    LLMConfig,
    ScheduleConfig,
    WatchlistConfig,
)
from src.storage.database import Database
from src.storage.models import Base


@pytest.fixture
def sample_config():
    """Minimal valid config for testing."""
    return AppConfig(
        watchlist=WatchlistConfig(
            a_shares=["600519"],
            funds=["510300"],
            hk_stocks=["00700"],
            us_stocks=["AAPL"],
        ),
        llm=LLMConfig(provider="openai", model="gpt-4o-mini", api_key="test-key"),
        email=EmailConfig(
            smtp_host="smtp.qq.com",
            smtp_port=465,
            sender="test@qq.com",
            password="test",
            recipients=["test@qq.com"],
        ),
        schedule=ScheduleConfig(),
        alerts=AlertConfig(),
        database=DatabaseConfig(path=":memory:"),
    )


@pytest.fixture
def test_db():
    """In-memory SQLite database with all tables."""
    db = Database.__new__(Database)
    db.engine = create_engine("sqlite:///:memory:")
    db._SessionFactory = sessionmaker(bind=db.engine)
    Base.metadata.create_all(db.engine)
    return db


@pytest.fixture
def mock_llm(mocker):
    """Mock LLM that returns predictable JSON responses."""
    mock = mocker.patch("litellm.completion")
    mock.return_value.choices = [
        mocker.Mock(
            message=mocker.Mock(
                content='{"summary":"测试分析","rating":"neutral","confidence":0.5}'
            )
        )
    ]
    return mock
