from __future__ import annotations

from typing import Dict, Tuple, Type

from backend.adapters.base import BaseAdapter


_REGISTRY: Dict[Tuple[str, str], Type[BaseAdapter]] = {}


class AdapterNotFoundError(ValueError):
    pass


def register(source: str, report_type: str, adapter_cls: Type[BaseAdapter]) -> None:
    if not issubclass(adapter_cls, BaseAdapter):
        raise TypeError(
            f"Adapter class must be a subclass of BaseAdapter, got {adapter_cls!r}"
        )
    _REGISTRY[(source, report_type)] = adapter_cls


def get_adapter(source: str, report_type: str) -> Type[BaseAdapter]:
    key = (source, report_type)
    if key not in _REGISTRY:
        raise AdapterNotFoundError(
            f"No adapter registered for source={source}, report_type={report_type}"
        )
    return _REGISTRY[key]


def list_adapters() -> Dict[Tuple[str, str], Type[BaseAdapter]]:
    return dict(_REGISTRY)


from backend.adapters.binance.transaction_record import BinanceTransactionRecordAdapter
from backend.adapters.binance.spot_trade_history import BinanceSpotTradeHistoryAdapter
from backend.adapters.coinbase.transaction_record import CoinbaseTransactionRecordAdapter

register("binance", "transaction_record", BinanceTransactionRecordAdapter)
register("binance", "spot_trade_history", BinanceSpotTradeHistoryAdapter)
register("coinbase", "transaction_record", CoinbaseTransactionRecordAdapter)
