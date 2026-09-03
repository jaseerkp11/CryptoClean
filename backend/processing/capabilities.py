from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional, Set


class ReportCapability(str, Enum):
    TRANSACTION_ACTIVITY = "transaction_activity"
    TRADE_EXECUTION = "trade_execution"
    ASSET_QUANTITY = "asset_quantity"
    FIAT_VALUE = "fiat_value"
    TRADE_PRICE = "trade_price"
    FEE = "fee"
    TRANSFER_INFORMATION = "transfer_information"
    DEPOSIT_INFORMATION = "deposit_information"
    WITHDRAWAL_INFORMATION = "withdrawal_information"
    REWARD_INFORMATION = "reward_information"
    TRANSACTION_IDENTIFIER = "transaction_identifier"
    TIMESTAMP = "timestamp"


REPORT_CAPABILITIES: Dict[str, Set[ReportCapability]] = {
    "binance_transaction_record": {
        ReportCapability.TRANSACTION_ACTIVITY,
        ReportCapability.TRANSFER_INFORMATION,
        ReportCapability.DEPOSIT_INFORMATION,
        ReportCapability.WITHDRAWAL_INFORMATION,
        ReportCapability.FEE,
        ReportCapability.REWARD_INFORMATION,
        ReportCapability.TRANSACTION_IDENTIFIER,
        ReportCapability.TIMESTAMP,
    },
    "binance_spot_trade_history": {
        ReportCapability.TRADE_EXECUTION,
        ReportCapability.ASSET_QUANTITY,
        ReportCapability.TRADE_PRICE,
        ReportCapability.FIAT_VALUE,
        ReportCapability.FEE,
        ReportCapability.TRANSACTION_IDENTIFIER,
        ReportCapability.TIMESTAMP,
    },
    "coinbase_transaction_record": {
        ReportCapability.TRANSACTION_ACTIVITY,
        ReportCapability.TRADE_EXECUTION,
        ReportCapability.ASSET_QUANTITY,
        ReportCapability.TRADE_PRICE,
        ReportCapability.FIAT_VALUE,
        ReportCapability.FEE,
        ReportCapability.TRANSFER_INFORMATION,
        ReportCapability.DEPOSIT_INFORMATION,
        ReportCapability.WITHDRAWAL_INFORMATION,
        ReportCapability.REWARD_INFORMATION,
        ReportCapability.TRANSACTION_IDENTIFIER,
        ReportCapability.TIMESTAMP,
    },
}

REPORT_PRIORITY: Dict[str, int] = {
    "binance_spot_trade_history": 1,
    "coinbase_transaction_record": 2,
    "binance_transaction_record": 3,
}


def get_report_capabilities(report_type: str) -> Set[ReportCapability]:
    return REPORT_CAPABILITIES.get(report_type, set())


def get_report_priority(report_type: str) -> int:
    return REPORT_PRIORITY.get(report_type, 999)


def compute_readiness(
    transactions: List[Any],
    accounting_result: Optional[Any] = None,
    warnings: Optional[List[Any]] = None,
    errors: Optional[List[Any]] = None,
) -> tuple[str, Dict[str, any]]:
    if errors and not transactions:
        return "INCOMPLETE_SOURCE_DATA", {
            "transactions_detected": False,
            "reason": "Processing errors prevented analysis.",
        }

    details: Dict[str, any] = {
        "transactions_detected": len(transactions) > 0,
        "trade_pricing_available": False,
        "cost_basis_available": False,
        "proceeds_available": False,
        "realized_pnl_available": False,
        "warnings_count": len(warnings) if warnings else 0,
        "errors_count": len(errors) if errors else 0,
    }

    trade_count = 0
    trades_with_price = 0
    trades_with_value = 0
    disposals_with_proceeds = 0
    disposals_with_cost_basis = 0

    for tx in transactions:
        if tx.transaction_type.value == "TRADE":
            trade_count += 1
            if tx.price is not None:
                trades_with_price += 1
            if tx.value is not None:
                trades_with_value += 1

    if accounting_result and accounting_result.events:
        for event in accounting_result.events:
            if event.event_type.value == "DISPOSAL":
                if event.proceeds is not None:
                    disposals_with_proceeds += 1
                if event.cost_basis is not None:
                    disposals_with_cost_basis += 1

    details["trade_count"] = trade_count
    details["trades_with_price"] = trades_with_price
    details["trades_with_value"] = trades_with_value
    details["disposals_with_proceeds"] = disposals_with_proceeds
    details["disposals_with_cost_basis"] = disposals_with_cost_basis

    if trade_count > 0:
        details["trade_pricing_available"] = trades_with_price > 0 or trades_with_value > 0
        details["cost_basis_available"] = trades_with_price > 0 or trades_with_value > 0
        details["proceeds_available"] = trades_with_value > 0

    if accounting_result and accounting_result.realized_pnl:
        details["realized_pnl_available"] = any(
            pnl.total_realized_pnl is not None for pnl in accounting_result.realized_pnl
        )

    if details["errors_count"] > 0 and not transactions:
        return "INCOMPLETE_SOURCE_DATA", details

    if details["warnings_count"] > 0 or not details["trade_pricing_available"]:
        return "REVIEW_REQUIRED", details

    return "READY_FOR_REVIEW", details
