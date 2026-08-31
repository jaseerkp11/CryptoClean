import pytest

from backend.adapters.base import BaseAdapter
from backend.adapters.binance.transaction_record import BinanceTransactionRecordAdapter
from backend.adapters.binance.spot_trade_history import BinanceSpotTradeHistoryAdapter
from backend.adapters.coinbase.transaction_record import CoinbaseTransactionRecordAdapter
from backend.adapters.registry import (
    get_adapter,
    list_adapters,
    register,
    AdapterNotFoundError,
)


def test_binance_transaction_record_resolves():
    cls = get_adapter("binance", "transaction_record")
    assert cls is BinanceTransactionRecordAdapter


def test_binance_spot_trade_history_resolves():
    cls = get_adapter("binance", "spot_trade_history")
    assert cls is BinanceSpotTradeHistoryAdapter


def test_coinbase_transaction_record_resolves():
    cls = get_adapter("coinbase", "transaction_record")
    assert cls is CoinbaseTransactionRecordAdapter


def test_unsupported_source_report_type_raises():
    with pytest.raises(AdapterNotFoundError):
        get_adapter("bybit", "transaction_record")


def test_unsupported_report_type_for_known_source_raises():
    with pytest.raises(AdapterNotFoundError):
        get_adapter("binance", "unknown_report_type")


def test_registry_returns_class_not_instance():
    cls = get_adapter("binance", "transaction_record")
    assert isinstance(cls, type)
    assert issubclass(cls, BaseAdapter)


def test_registry_does_not_instantiate_on_lookup():
    cls = get_adapter("binance", "transaction_record")
    assert cls is BinanceTransactionRecordAdapter


def test_duplicate_registration_is_deterministic():
    from backend.adapters.registry import _REGISTRY

    key = ("binance", "transaction_record")
    original = _REGISTRY[key]
    register("binance", "transaction_record", BinanceTransactionRecordAdapter)
    assert _REGISTRY[key] is original


def test_list_adapters_contains_registered_entries():
    adapters = list_adapters()
    assert ("binance", "transaction_record") in adapters
    assert ("binance", "spot_trade_history") in adapters
    assert ("coinbase", "transaction_record") in adapters
