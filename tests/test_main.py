"""Tests for command-line handlers that persist local state."""

from argparse import Namespace

from src.config import AppConfig, DatabaseConfig
from src.main import _cmd_delete_holding, _cmd_set_holding
from src.storage.database import Database
from src.storage.queries import QueryService


def test_set_holding_command_persists_a_position(tmp_path):
    """The CLI handler saves a holding that is available to valuation queries."""
    config = AppConfig(database=DatabaseConfig(path=str(tmp_path / "investment.db")))
    args = Namespace(
        market="fund",
        symbol="510300",
        name="沪深300ETF",
        shares=1000.0,
        cost_price=3.85,
    )

    _cmd_set_holding(config, args)

    valuation = QueryService(Database(config.database)).get_portfolio_valuation()
    assert valuation["holdings"] == [
        {
            "market": "fund",
            "symbol": "510300",
            "name": "沪深300ETF",
            "shares": 1000.0,
            "cost_price": 3.85,
            "currency": "CNY",
            "latest_price": None,
            "price_date": None,
            "cost_value": 3850.0,
            "market_value": None,
            "unrealized_pnl": None,
            "unrealized_pnl_pct": None,
        }
    ]


def test_delete_holding_command_removes_a_position(tmp_path):
    """The CLI handler removes the precise holding selected by market and symbol."""
    config = AppConfig(database=DatabaseConfig(path=str(tmp_path / "investment.db")))
    set_args = Namespace(
        market="fund",
        symbol="510300",
        name="沪深300ETF",
        shares=1000.0,
        cost_price=3.85,
    )
    delete_args = Namespace(market="fund", symbol="510300")
    _cmd_set_holding(config, set_args)

    _cmd_delete_holding(config, delete_args)

    valuation = QueryService(Database(config.database)).get_portfolio_valuation()
    assert valuation["holdings"] == []