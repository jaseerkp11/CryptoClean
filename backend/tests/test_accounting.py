from __future__ import annotations

import io
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend.accounting.configuration import AccountingConfiguration, CostBasisMethodType
from backend.accounting.engine import AccountingEngine
from backend.accounting.exceptions import make_warning, make_exception
from backend.reconciliation.transfers import TransferReconciler
from backend.accounting.models import (
    AcquisitionLot,
    AccountingEvent,
    AccountingEventType,
    AccountingResult,
    AccountingSummary,
    AccountingWarning,
    AcquisitionType,
    ExceptionCode,
    LotConsumption,
    RealizedPnL,
    WarningCode,
)
from backend.main import app
from backend.models.transaction import (
    CanonicalTransaction,
    Side,
    Source,
    TransactionType,
)


def _tx(
    transaction_id,
    source=Source.BINANCE,
    timestamp=None,
    transaction_type=TransactionType.TRADE,
    side=Side.BUY,
    asset="BTC",
    quantity=Decimal("1"),
    quote_asset="USDT",
    price=Decimal("50000"),
    value=None,
    fee=None,
    fee_asset=None,
    wallet=None,
    counterparty=None,
    tx_hash=None,
    source_transaction_id=None,
    metadata=None,
):
    if timestamp is None:
        timestamp = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return CanonicalTransaction(
        transaction_id=transaction_id,
        source=source,
        source_transaction_id=source_transaction_id,
        timestamp=timestamp,
        transaction_type=transaction_type,
        side=side,
        asset=asset,
        quantity=quantity,
        quote_asset=quote_asset,
        price=price,
        value=value,
        fee=fee,
        fee_asset=fee_asset,
        wallet=wallet,
        counterparty=counterparty,
        tx_hash=tx_hash,
        confidence=1.0,
        metadata=metadata,
    )


# --- Models ---


def test_acquisition_lot_valid():
    lot = AcquisitionLot(
        lot_id="lot-1",
        asset="BTC",
        acquired_quantity=Decimal("1"),
        remaining_quantity=Decimal("1"),
        unit_cost=Decimal("50000"),
        total_cost=Decimal("50000"),
        cost_currency="USDT",
        acquired_timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        source_transaction_id="tx-1",
        acquisition_type=AcquisitionType.BUY,
        linked_event_id="evt-1",
    )
    assert lot.remaining_quantity == Decimal("1")


def test_acquisition_lot_invalid_negative_quantity():
    with pytest.raises(ValueError):
        AcquisitionLot(
            lot_id="lot-1",
            asset="BTC",
            acquired_quantity=Decimal("-1"),
            remaining_quantity=Decimal("-1"),
            acquired_timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            source_transaction_id="tx-1",
            acquisition_type=AcquisitionType.BUY,
            linked_event_id="evt-1",
        )


def test_acquisition_lot_invalid_remaining_exceeds_acquired():
    with pytest.raises(ValueError):
        AcquisitionLot(
            lot_id="lot-1",
            asset="BTC",
            acquired_quantity=Decimal("1"),
            remaining_quantity=Decimal("2"),
            acquired_timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            source_transaction_id="tx-1",
            acquisition_type=AcquisitionType.BUY,
            linked_event_id="evt-1",
        )


def test_lot_consumption_valid():
    c = LotConsumption(
        consumption_id="c-1",
        lot_id="lot-1",
        disposal_event_id="evt-1",
        asset="BTC",
        quantity_consumed=Decimal("0.5"),
        unit_cost=Decimal("50000"),
        cost_allocated=Decimal("25000"),
        cost_currency="USDT",
        consumed_timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
    )
    assert c.quantity_consumed == Decimal("0.5")


def test_lot_consumption_invalid_zero_quantity():
    with pytest.raises(ValueError):
        LotConsumption(
            consumption_id="c-1",
            lot_id="lot-1",
            disposal_event_id="evt-1",
            asset="BTC",
            quantity_consumed=Decimal("0"),
            unit_cost=Decimal("50000"),
            cost_allocated=Decimal("0"),
            cost_currency="USDT",
            consumed_timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        )


def test_accounting_warning_deterministic_id():
    w1 = make_warning(
        code=WarningCode.MISSING_COST_BASIS,
        message="no cost",
        source_transaction_id="tx-1",
    )
    w2 = make_warning(
        code=WarningCode.MISSING_COST_BASIS,
        message="no cost",
        source_transaction_id="tx-1",
    )
    assert w1.warning_id == w2.warning_id


def test_accounting_event_quantity_positive():
    with pytest.raises(ValueError):
        AccountingEvent(
            event_id="evt-1",
            event_type=AccountingEventType.ACQUISITION,
            source_transaction_ids=["tx-1"],
            timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            asset="BTC",
            quantity=Decimal("0"),
        )


# --- FIFO Engine ---


def test_fifo_one_lot_full_disposal():
    tx_buy = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"))
    tx_sell = _tx("tx-2", side=Side.SELL, quantity=Decimal("1"), price=Decimal("60000"), value=Decimal("60000"))
    engine = AccountingEngine()
    result = engine.process([tx_buy, tx_sell])
    assert len(result.lots) == 1
    assert result.lots[0].remaining_quantity == Decimal("0")
    assert len(result.consumptions) == 1
    assert result.consumptions[0].quantity_consumed == Decimal("1")
    assert result.consumptions[0].cost_allocated == Decimal("50000")


def test_fifo_one_lot_partial_disposal():
    tx_buy = _tx("tx-1", side=Side.BUY, quantity=Decimal("10"), price=Decimal("40000"), value=Decimal("400000"))
    tx_sell = _tx("tx-2", side=Side.SELL, quantity=Decimal("3"), price=Decimal("40000"), value=Decimal("120000"))
    engine = AccountingEngine()
    result = engine.process([tx_buy, tx_sell])
    assert len(result.lots) == 1
    assert result.lots[0].remaining_quantity == Decimal("7")
    assert len(result.consumptions) == 1
    assert result.consumptions[0].quantity_consumed == Decimal("3")
    assert result.consumptions[0].cost_allocated == Decimal("120000")


def test_fifo_multiple_lots():
    tx_buy1 = _tx("tx-1", side=Side.BUY, quantity=Decimal("2"), price=Decimal("40000"), value=Decimal("80000"), timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc))
    tx_buy2 = _tx("tx-2", side=Side.BUY, quantity=Decimal("3"), price=Decimal("45000"), value=Decimal("135000"), timestamp=datetime(2024, 1, 2, 0, 0, 0, tzinfo=timezone.utc))
    tx_sell = _tx("tx-3", side=Side.SELL, quantity=Decimal("4"), price=Decimal("50000"), value=Decimal("200000"), timestamp=datetime(2024, 1, 3, 0, 0, 0, tzinfo=timezone.utc))
    engine = AccountingEngine()
    result = engine.process([tx_buy1, tx_buy2, tx_sell])
    assert len(result.lots) == 2
    assert result.lots[0].remaining_quantity == Decimal("0")
    assert result.lots[1].remaining_quantity == Decimal("1")
    assert len(result.consumptions) == 2
    assert result.consumptions[0].lot_id == result.lots[0].lot_id
    assert result.consumptions[0].quantity_consumed == Decimal("2")
    assert result.consumptions[1].lot_id == result.lots[1].lot_id
    assert result.consumptions[1].quantity_consumed == Decimal("2")


def test_fifo_insufficient_lots():
    tx_buy = _tx("tx-1", side=Side.BUY, quantity=Decimal("2"), price=Decimal("40000"), value=Decimal("80000"))
    tx_sell = _tx("tx-2", side=Side.SELL, quantity=Decimal("5"), price=Decimal("50000"), value=Decimal("250000"))
    engine = AccountingEngine()
    result = engine.process([tx_buy, tx_sell])
    assert len(result.consumptions) == 1
    assert result.consumptions[0].quantity_consumed == Decimal("2")
    assert result.consumptions[0].cost_allocated == Decimal("80000")
    assert any(e.code == ExceptionCode.INSUFFICIENT_LOTS_FOR_DISPOSAL for e in result.errors)


def test_fifo_zero_disposal_skipped():
    tx_buy = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"))
    tx_sell = _tx("tx-2", side=Side.SELL, quantity=Decimal("0.00000001"), price=Decimal("50000"), value=Decimal("0.0005"))
    engine = AccountingEngine()
    result = engine.process([tx_buy, tx_sell])
    assert len(result.consumptions) == 1
    assert result.consumptions[0].quantity_consumed == Decimal("0.00000001")


def test_fifo_identical_timestamps_deterministic():
    ts = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    tx_buy1 = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("40000"), value=Decimal("40000"), timestamp=ts)
    tx_buy2 = _tx("tx-2", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"), timestamp=ts)
    tx_sell = _tx("tx-3", side=Side.SELL, quantity=Decimal("1"), price=Decimal("60000"), value=Decimal("60000"), timestamp=ts)
    result1 = AccountingEngine().process([tx_buy1, tx_buy2, tx_sell])
    result2 = AccountingEngine().process([tx_buy1, tx_buy2, tx_sell])
    assert result1.consumptions[0].lot_id == result2.consumptions[0].lot_id
    assert result1.events == result2.events


# --- Transaction semantics ---


def test_buy_creates_acquisition():
    tx = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"))
    engine = AccountingEngine()
    result = engine.process([tx])
    assert len(result.events) == 1
    assert result.events[0].event_type == AccountingEventType.ACQUISITION
    assert len(result.lots) == 1
    assert result.lots[0].unit_cost == Decimal("50000")
    assert result.summary.acquisition_events == 1


def test_sell_creates_disposal():
    tx_buy = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"))
    tx_sell = _tx("tx-2", side=Side.SELL, quantity=Decimal("1"), price=Decimal("60000"), value=Decimal("60000"))
    engine = AccountingEngine()
    result = engine.process([tx_buy, tx_sell])
    assert len(result.events) == 2
    assert result.events[1].event_type == AccountingEventType.DISPOSAL
    assert result.summary.disposal_events == 1


def test_deposit_with_known_cost():
    tx = _tx("tx-1", transaction_type=TransactionType.DEPOSIT, side=None, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"))
    engine = AccountingEngine()
    result = engine.process([tx])
    assert len(result.events) == 1
    assert result.events[0].event_type == AccountingEventType.ACQUISITION
    assert len(result.lots) == 1
    assert result.lots[0].unit_cost == Decimal("50000")


def test_deposit_without_cost_produces_warning():
    tx = _tx("tx-1", transaction_type=TransactionType.DEPOSIT, side=None, quantity=Decimal("1"), price=None, value=None)
    engine = AccountingEngine()
    result = engine.process([tx])
    assert len(result.lots) == 1
    assert result.lots[0].unit_cost is None
    assert any(w.code == WarningCode.MISSING_COST_BASIS for w in result.warnings)


def test_withdrawal_is_disposal():
    tx = _tx("tx-1", transaction_type=TransactionType.WITHDRAWAL, side=None, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"))
    engine = AccountingEngine()
    result = engine.process([tx])
    assert len(result.events) == 1
    assert result.events[0].event_type == AccountingEventType.DISPOSAL
    assert result.events[0].proceeds == Decimal("50000")
    assert not any(w.code == WarningCode.WITHDRAWAL_NO_PROCEEDS for w in result.warnings)


def test_withdrawal_no_value_produces_warning():
    tx = _tx("tx-2", transaction_type=TransactionType.WITHDRAWAL, side=None, quantity=Decimal("1"), price=None, value=None)
    engine = AccountingEngine()
    result = engine.process([tx])
    assert len(result.events) == 1
    assert result.events[0].event_type == AccountingEventType.DISPOSAL
    assert result.events[0].proceeds == Decimal("0")
    assert any(w.code == WarningCode.WITHDRAWAL_NO_PROCEEDS for w in result.warnings)


def test_transfer_matched_no_lots():
    tx = _tx("tx-1", transaction_type=TransactionType.TRANSFER, side=None, quantity=Decimal("1"), asset="USDT")
    engine = AccountingEngine()
    result = engine.process([tx], transfer_result=type("T", (), {"matches": [type("M", (), {"leg_a_transaction_id": "tx-1", "leg_b_transaction_id": "tx-2"})()]})())
    assert len(result.events) == 1
    assert result.events[0].event_type == AccountingEventType.TRANSFER
    assert len(result.lots) == 0


def test_transfer_unmatched_produces_warning():
    tx = _tx("tx-1", transaction_type=TransactionType.TRANSFER, side=None, quantity=Decimal("1"), asset="USDT")
    engine = AccountingEngine()
    result = engine.process([tx])
    assert any(w.code == WarningCode.UNMATCHED_TRANSFER for w in result.warnings)


def test_swap_deferred():
    tx = _tx("tx-1", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("1"), asset="BTC")
    engine = AccountingEngine()
    result = engine.process([tx])
    assert len(result.events) == 1
    assert result.events[0].event_type == AccountingEventType.NON_ACCOUNTING
    assert any(w.code == WarningCode.PARTIAL_SWAP_VALUATION for w in result.warnings)


def test_unknown_non_accounting():
    tx = _tx("tx-1", transaction_type=TransactionType.UNKNOWN, side=None, quantity=Decimal("1"), asset="XRP")
    engine = AccountingEngine()
    result = engine.process([tx])
    assert len(result.events) == 1
    assert result.events[0].event_type == AccountingEventType.NON_ACCOUNTING
    assert any(w.code == WarningCode.UNKNOWN_TRANSACTION_TYPE for w in result.warnings)


# --- Decimal integrity ---


def test_decimal_precision_preserved():
    tx_buy = _tx("tx-1", side=Side.BUY, quantity=Decimal("0.12345678"), price=Decimal("12345.6789"), value=Decimal("1525.89"))
    tx_sell = _tx("tx-2", side=Side.SELL, quantity=Decimal("0.12345678"), price=Decimal("20000"), value=Decimal("2469.13"))
    engine = AccountingEngine()
    result = engine.process([tx_buy, tx_sell])
    assert result.consumptions[0].cost_allocated == Decimal("1525.89")
    assert result.events[1].proceeds == Decimal("2469.13")


def test_no_float_arithmetic():
    tx_buy = _tx("tx-1", side=Side.BUY, quantity=Decimal("0.1"), price=Decimal("0.2"), value=Decimal("0.02"))
    engine = AccountingEngine()
    result = engine.process([tx_buy])
    assert isinstance(result.lots[0].unit_cost, Decimal)
    assert result.lots[0].unit_cost == Decimal("0.2")


# --- Determinism ---


def test_deterministic_result():
    tx_buy = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"))
    tx_sell = _tx("tx-2", side=Side.SELL, quantity=Decimal("1"), price=Decimal("60000"), value=Decimal("60000"))
    r1 = AccountingEngine().process([tx_buy, tx_sell])
    r2 = AccountingEngine().process([tx_buy, tx_sell])
    assert r1.events == r2.events
    assert r1.lots == r2.lots
    assert r1.consumptions == r2.consumptions
    assert r1.warnings == r2.warnings
    assert r1.errors == r2.errors


# --- Immutability ---


def test_canonical_transaction_not_mutated():
    tx = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"))
    original = tx.model_dump()
    AccountingEngine().process([tx])
    assert tx.model_dump() == original


# --- Partial consumption ---


def test_partial_then_full_consumption():
    tx_buy = _tx("tx-1", side=Side.BUY, quantity=Decimal("10"), price=Decimal("40000"), value=Decimal("400000"))
    tx_sell1 = _tx("tx-2", side=Side.SELL, quantity=Decimal("3"), price=Decimal("40000"), value=Decimal("120000"))
    tx_sell2 = _tx("tx-3", side=Side.SELL, quantity=Decimal("5"), price=Decimal("40000"), value=Decimal("200000"))
    engine = AccountingEngine()
    result = engine.process([tx_buy, tx_sell1, tx_sell2])
    assert len(result.lots) == 1
    assert result.lots[0].remaining_quantity == Decimal("2")
    assert len(result.consumptions) == 2
    assert result.consumptions[0].quantity_consumed == Decimal("3")
    assert result.consumptions[1].quantity_consumed == Decimal("5")


# --- Insufficient lots ---


def test_insufficient_lots_does_not_go_negative():
    tx_buy = _tx("tx-1", side=Side.BUY, quantity=Decimal("2"), price=Decimal("40000"), value=Decimal("80000"))
    tx_sell = _tx("tx-2", side=Side.SELL, quantity=Decimal("5"), price=Decimal("50000"), value=Decimal("250000"))
    engine = AccountingEngine()
    result = engine.process([tx_buy, tx_sell])
    assert result.lots[0].remaining_quantity == Decimal("0")
    assert any(e.code == ExceptionCode.INSUFFICIENT_LOTS_FOR_DISPOSAL for e in result.errors)


# --- Missing cost / proceeds ---


def test_missing_cost_basis():
    tx = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=None, value=None)
    engine = AccountingEngine()
    result = engine.process([tx])
    assert result.lots[0].unit_cost is None
    assert any(w.code == WarningCode.MISSING_COST_BASIS for w in result.warnings)


def test_missing_proceeds():
    tx_buy = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"))
    tx_sell = _tx("tx-2", side=Side.SELL, quantity=Decimal("1"), price=None, value=None)
    engine = AccountingEngine()
    result = engine.process([tx_buy, tx_sell])
    assert result.events[1].proceeds is None
    assert any(w.code == WarningCode.MISSING_PROCEEDS for w in result.warnings)


# --- Configuration ---


def test_configuration_defaults():
    config = AccountingConfiguration()
    assert config.cost_basis_method == CostBasisMethodType.FIFO
    assert config.reporting_currency is None
    assert config.timezone == "UTC"


def test_configuration_invalid_blank_currency():
    with pytest.raises(ValueError):
        AccountingConfiguration(reporting_currency="   ")


# --- Summary ---


def test_summary_counts():
    tx_buy = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"))
    tx_sell = _tx("tx-2", side=Side.SELL, quantity=Decimal("1"), price=Decimal("60000"), value=Decimal("60000"))
    tx_deposit = _tx("tx-3", transaction_type=TransactionType.DEPOSIT, side=None, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"))
    tx_transfer = _tx("tx-4", transaction_type=TransactionType.TRANSFER, side=None, quantity=Decimal("1"), asset="USDT")
    tx_swap = _tx("tx-5", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("1"), asset="BTC")
    tx_unknown = _tx("tx-6", transaction_type=TransactionType.UNKNOWN, side=None, quantity=Decimal("1"), asset="XRP")
    engine = AccountingEngine()
    result = engine.process([tx_buy, tx_sell, tx_deposit, tx_transfer, tx_swap, tx_unknown])
    assert result.summary.total_events == 6
    assert result.summary.acquisition_events == 2
    assert result.summary.disposal_events == 1
    assert result.summary.transfer_events == 1
    assert result.summary.swap_events == 0  # swap is non-accounting in M020-A
    assert result.summary.total_lots_created == 2


# --- Fees ---


def test_quote_asset_fee_on_buy_increases_cost():
    tx = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"), fee=Decimal("10"), fee_asset="USDT")
    engine = AccountingEngine()
    result = engine.process([tx])
    assert result.lots[0].unit_cost == Decimal("50010")
    assert result.lots[0].total_cost == Decimal("50010")


def test_quote_asset_fee_on_sell_reduces_proceeds():
    tx_buy = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"))
    tx_sell = _tx("tx-2", side=Side.SELL, quantity=Decimal("1"), price=Decimal("60000"), value=Decimal("60000"), fee=Decimal("10"), fee_asset="USDT")
    engine = AccountingEngine()
    result = engine.process([tx_buy, tx_sell])
    assert result.events[1].proceeds == Decimal("59990")


def test_base_asset_fee_on_buy_reduces_quantity():
    tx = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"), fee=Decimal("0.01"), fee_asset="BTC")
    engine = AccountingEngine()
    result = engine.process([tx])
    assert result.lots[0].acquired_quantity == Decimal("0.99")
    assert result.lots[0].unit_cost == Decimal("50000")


def test_base_asset_fee_on_sell_reduces_disposal_quantity():
    tx_buy = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"))
    tx_sell = _tx("tx-2", side=Side.SELL, quantity=Decimal("1"), price=Decimal("60000"), value=Decimal("60000"), fee=Decimal("0.01"), fee_asset="BTC")
    engine = AccountingEngine()
    result = engine.process([tx_buy, tx_sell])
    assert result.events[1].quantity == Decimal("0.99")
    assert result.consumptions[0].quantity_consumed == Decimal("0.99")


def test_third_asset_fee_produces_warning():
    tx = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"), fee=Decimal("0.5"), fee_asset="BNB")
    engine = AccountingEngine()
    result = engine.process([tx])
    assert result.lots[0].unit_cost == Decimal("50000")
    assert any(w.code == WarningCode.THIRD_ASSET_FEE for w in result.warnings)


def test_missing_fee_asset_produces_warning():
    tx = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"), fee=Decimal("10"), fee_asset=None)
    engine = AccountingEngine()
    result = engine.process([tx])
    assert result.lots[0].unit_cost == Decimal("50000")
    assert any(w.code == WarningCode.MISSING_FEE_ASSET for w in result.warnings)


def test_zero_fee_unchanged():
    tx_buy = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"), fee=Decimal("0"), fee_asset="USDT")
    tx_sell = _tx("tx-2", side=Side.SELL, quantity=Decimal("1"), price=Decimal("60000"), value=Decimal("60000"), fee=Decimal("0"), fee_asset="USDT")
    engine = AccountingEngine()
    result = engine.process([tx_buy, tx_sell])
    assert result.lots[0].unit_cost == Decimal("50000")
    assert result.events[1].proceeds == Decimal("60000")


def test_no_fee_unchanged():
    tx_buy = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"), fee=None, fee_asset=None)
    tx_sell = _tx("tx-2", side=Side.SELL, quantity=Decimal("1"), price=Decimal("60000"), value=Decimal("60000"), fee=None, fee_asset=None)
    engine = AccountingEngine()
    result = engine.process([tx_buy, tx_sell])
    assert result.lots[0].unit_cost == Decimal("50000")
    assert result.events[1].proceeds == Decimal("60000")


def test_fee_decimal_precision():
    tx = _tx("tx-1", side=Side.BUY, quantity=Decimal("0.12345678"), price=Decimal("12345.6789"), value=Decimal("1525.89"), fee=Decimal("0.01"), fee_asset="USDT")
    engine = AccountingEngine()
    result = engine.process([tx])
    assert result.lots[0].unit_cost == Decimal("12359.71001349622110669013075") + Decimal("0.01") / Decimal("0.12345678")


# --- Transfers ---


def test_matched_transfer_preserves_lot_linkage():
    tx = _tx("tx-1", transaction_type=TransactionType.TRANSFER, side=None, quantity=Decimal("1"), asset="USDT")
    transfer_result = type("T", (), {"matches": [type("M", (), {"source_transaction_id": "tx-1", "destination_transaction_id": "tx-2"})()]})()
    engine = AccountingEngine()
    result = engine.process([tx], transfer_result=transfer_result)
    assert len(result.events) == 1
    assert result.events[0].event_type == AccountingEventType.TRANSFER
    assert result.events[0].linked_event_ids == ["tx-2"]
    assert len(result.lots) == 0


def test_unmatched_transfer_produces_warning():
    tx = _tx("tx-1", transaction_type=TransactionType.TRANSFER, side=None, quantity=Decimal("1"), asset="USDT")
    engine = AccountingEngine()
    result = engine.process([tx])
    assert any(w.code == WarningCode.UNMATCHED_TRANSFER for w in result.warnings)


def test_transfer_no_lots_created():
    tx = _tx("tx-1", transaction_type=TransactionType.TRANSFER, side=None, quantity=Decimal("1"), asset="USDT")
    transfer_result = type("T", (), {"matches": [type("M", (), {"source_transaction_id": "tx-1", "destination_transaction_id": "tx-2"})()]})()
    engine = AccountingEngine()
    result = engine.process([tx], transfer_result=transfer_result)
    assert len(result.lots) == 0
    assert len(result.consumptions) == 0


def test_transfer_deterministic():
    tx = _tx("tx-1", transaction_type=TransactionType.TRANSFER, side=None, quantity=Decimal("1"), asset="USDT")
    transfer_result = type("T", (), {"matches": [type("M", (), {"source_transaction_id": "tx-1", "destination_transaction_id": "tx-2"})()]})()
    r1 = AccountingEngine().process([tx], transfer_result=transfer_result)
    r2 = AccountingEngine().process([tx], transfer_result=transfer_result)
    assert r1.events == r2.events


# --- Swaps ---


def test_swap_pair_creates_disposal_and_acquisition():
    tx_out = _tx("tx-1", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("1"), asset="BTC", price=Decimal("50000"), value=Decimal("50000"))
    tx_in = _tx("tx-2", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("0.5"), asset="ETH", price=Decimal("1000"), value=Decimal("500"))
    engine = AccountingEngine()
    result = engine.process([tx_out, tx_in])
    assert len(result.events) == 2
    assert result.events[0].event_type == AccountingEventType.DISPOSAL
    assert result.events[1].event_type == AccountingEventType.ACQUISITION
    assert result.summary.acquisition_events == 1
    assert result.summary.disposal_events == 1


def test_swap_disposal_consumes_fifo_lot():
    tx_buy = _tx("tx-0", side=Side.BUY, quantity=Decimal("1"), price=Decimal("40000"), value=Decimal("40000"))
    tx_out = _tx("tx-1", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("1"), asset="BTC", price=Decimal("50000"), value=Decimal("50000"))
    tx_in = _tx("tx-2", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("0.5"), asset="ETH", price=Decimal("1000"), value=Decimal("500"))
    engine = AccountingEngine()
    result = engine.process([tx_buy, tx_out, tx_in])
    assert len(result.consumptions) == 1
    assert result.consumptions[0].lot_id == result.lots[0].lot_id
    assert result.lots[0].remaining_quantity == Decimal("0")


def test_swap_acquisition_creates_lot():
    tx_out = _tx("tx-1", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("1"), asset="BTC", price=Decimal("50000"), value=Decimal("50000"))
    tx_in = _tx("tx-2", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("0.5"), asset="ETH", price=Decimal("1000"), value=Decimal("500"))
    engine = AccountingEngine()
    result = engine.process([tx_out, tx_in])
    assert len(result.lots) == 1
    assert result.lots[0].asset == "ETH"
    assert result.lots[0].unit_cost == Decimal("1000")


def test_swap_missing_proceeds_produces_warning():
    tx_out = _tx("tx-1", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("1"), asset="BTC", price=None, value=None)
    tx_in = _tx("tx-2", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("0.5"), asset="ETH", price=Decimal("1000"), value=Decimal("500"))
    engine = AccountingEngine()
    result = engine.process([tx_out, tx_in])
    assert result.events[0].proceeds is None
    assert any(w.code == WarningCode.MISSING_PROCEEDS for w in result.warnings)


def test_swap_no_fabricated_pnl():
    tx_buy = _tx("tx-0", side=Side.BUY, quantity=Decimal("1"), price=Decimal("40000"), value=Decimal("40000"))
    tx_out = _tx("tx-1", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("1"), asset="BTC", price=Decimal("50000"), value=Decimal("50000"))
    tx_in = _tx("tx-2", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("0.5"), asset="ETH", price=Decimal("1000"), value=Decimal("500"))
    engine = AccountingEngine()
    result = engine.process([tx_buy, tx_out, tx_in])
    assert result.events[0].realized_pnl is None


def test_swap_deterministic():
    tx_out = _tx("tx-1", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("1"), asset="BTC", price=Decimal("50000"), value=Decimal("50000"))
    tx_in = _tx("tx-2", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("0.5"), asset="ETH", price=Decimal("1000"), value=Decimal("500"))
    r1 = AccountingEngine().process([tx_out, tx_in])
    r2 = AccountingEngine().process([tx_out, tx_in])
    assert r1.events == r2.events
    assert r1.lots == r2.lots


def test_canonical_transaction_not_mutated_by_swap():
    tx_out = _tx("tx-1", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("1"), asset="BTC")
    tx_in = _tx("tx-2", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("0.5"), asset="ETH")
    original = [tx_out.model_dump(), tx_in.model_dump()]
    AccountingEngine().process([tx_out, tx_in])
    assert tx_out.model_dump() == original[0]
    assert tx_in.model_dump() == original[1]


def test_binance_convert_integration():
    from backend.reconciliation.converts import ConvertFinding
    tx_input = _tx("tx-in", transaction_type=TransactionType.UNKNOWN, side=None, quantity=Decimal("1"), asset="BTC", price=Decimal("50000"), value=Decimal("50000"), metadata={"source_operation": "Binance Convert"})
    tx_output = _tx("tx-out", transaction_type=TransactionType.UNKNOWN, side=None, quantity=Decimal("0.5"), asset="ETH", price=Decimal("1000"), value=Decimal("500"), metadata={"source_operation": "Binance Convert"})
    convert_finding = ConvertFinding(
        convert_id="cf-1",
        source="binance",
        timestamp=tx_input.timestamp,
        input_transaction_id="tx-in",
        output_transaction_id="tx-out",
        input_asset="BTC",
        input_quantity=Decimal("1"),
        output_asset="ETH",
        output_quantity=Decimal("0.5"),
        account="Spot",
        confidence=100,
        reasons=["test"],
        warnings=[],
    )
    convert_result = type("C", (), {"matches": [convert_finding]})()
    engine = AccountingEngine()
    result = engine.process([tx_input, tx_output], convert_result=convert_result)
    assert len(result.events) == 2
    assert result.events[0].event_type == AccountingEventType.DISPOSAL
    assert result.events[1].event_type == AccountingEventType.ACQUISITION
    assert result.lots[0].asset == "ETH"


def test_sell_creates_realized_pnl():
    tx_buy = _tx("tx-0", side=Side.BUY, quantity=Decimal("1"), price=Decimal("40000"), value=Decimal("40000"))
    tx_sell = _tx("tx-1", side=Side.SELL, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"))
    engine = AccountingEngine()
    result = engine.process([tx_buy, tx_sell])
    assert len(result.realized_pnl) == 1
    pnl = result.realized_pnl[0]
    assert pnl.total_realized_pnl == Decimal("10000")
    assert pnl.currency == "USDT"


def test_multiple_disposals_aggregate_pnl():
    tx_buy = _tx("tx-0", side=Side.BUY, quantity=Decimal("2"), price=Decimal("40000"), value=Decimal("80000"))
    tx_sell1 = _tx("tx-1", side=Side.SELL, quantity=Decimal("1"), price=Decimal("45000"), value=Decimal("45000"))
    tx_sell2 = _tx("tx-2", side=Side.SELL, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"))
    engine = AccountingEngine()
    result = engine.process([tx_buy, tx_sell1, tx_sell2])
    assert len(result.realized_pnl) == 1
    assert result.realized_pnl[0].total_realized_pnl == Decimal("15000")
    assert result.summary.total_realized_pnl == Decimal("15000")


def test_no_disposals_no_realized_pnl():
    tx_buy = _tx("tx-0", side=Side.BUY, quantity=Decimal("1"), price=Decimal("40000"), value=Decimal("40000"))
    engine = AccountingEngine()
    result = engine.process([tx_buy])
    assert len(result.realized_pnl) == 0
    assert result.summary.total_realized_pnl is None


def test_swap_realized_pnl():
    tx_buy = _tx("tx-0", side=Side.BUY, quantity=Decimal("1"), price=Decimal("40000"), value=Decimal("40000"))
    tx_out = _tx("tx-1", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("1"), asset="BTC", price=Decimal("50000"), value=Decimal("50000"))
    tx_in = _tx("tx-2", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("0.5"), asset="ETH", price=Decimal("1000"), value=Decimal("500"))
    engine = AccountingEngine()
    result = engine.process([tx_buy, tx_out, tx_in])
    assert len(result.realized_pnl) == 1
    assert result.realized_pnl[0].total_realized_pnl == Decimal("10000")


def test_consumption_realized_pnl_proportional_allocation():
    tx_buy1 = _tx("tx-0", side=Side.BUY, quantity=Decimal("1"), price=Decimal("40000"), value=Decimal("40000"), timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc))
    tx_buy2 = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("41000"), value=Decimal("41000"), timestamp=datetime(2024, 1, 1, 0, 0, 1, tzinfo=timezone.utc))
    tx_sell = _tx("tx-2", side=Side.SELL, quantity=Decimal("1.5"), price=Decimal("50000"), value=Decimal("75000"))
    engine = AccountingEngine()
    result = engine.process([tx_buy1, tx_buy2, tx_sell])
    assert len(result.realized_pnl) == 1
    assert result.realized_pnl[0].total_realized_pnl == Decimal("14500")


def test_api_account_endpoint():
    from fastapi.testclient import TestClient
    client = TestClient(app)
    csv_content = "Date(UTC),Pair,Type,Order Price,Amount,Average Price,Filled,Total,Fee,Fee Coin\n2024-01-01 12:00:00,BTC/USDT,Buy,30000,0.01,30000,0.01,300,0.1,BNB\n2024-01-02 12:00:00,BTC/USDT,Sell,31000,0.01,31000,0.01,310,0.1,BNB\n"
    files = {"file": ("binance_export.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/account?timezone=UTC", files=files)
    assert response.status_code == 200
    data = response.json()
    assert "accounting_result" in data
    assert len(data["accounting_result"]["events"]) == 2
    assert len(data["accounting_result"]["lots"]) == 1
    assert len(data["accounting_result"]["realized_pnl"]) == 1


def test_api_process_with_accounting_flag():
    from fastapi.testclient import TestClient
    client = TestClient(app)
    csv_content = "Date(UTC),Pair,Type,Order Price,Amount,Average Price,Filled,Total,Fee,Fee Coin\n2024-01-01 12:00:00,BTC/USDT,Buy,30000,0.01,30000,0.01,300,0.1,BNB\n2024-01-02 12:00:00,BTC/USDT,Sell,31000,0.01,31000,0.01,310,0.1,BNB\n"
    files = {"file": ("binance_export.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/process?timezone=UTC&accounting=true", files=files)
    assert response.status_code == 200
    data = response.json()
    assert "accounting_result" in data
    assert len(data["accounting_result"]["events"]) == 2


# --- P0-1: Fee must not fabricate missing acquisition cost basis ---


def test_quote_asset_fee_with_missing_cost_basis_does_not_fabricate():
    tx = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=None, value=None, fee=Decimal("10"), fee_asset="USDT")
    engine = AccountingEngine()
    result = engine.process([tx])
    assert result.lots[0].unit_cost is None
    assert result.lots[0].total_cost is None
    assert any(w.code == WarningCode.MISSING_COST_BASIS for w in result.warnings)


def test_base_asset_fee_with_missing_cost_basis_does_not_fabricate():
    tx = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=None, value=None, fee=Decimal("0.01"), fee_asset="BTC")
    engine = AccountingEngine()
    result = engine.process([tx])
    assert result.lots[0].unit_cost is None
    assert result.lots[0].total_cost is None
    assert any(w.code == WarningCode.MISSING_COST_BASIS for w in result.warnings)


def test_third_asset_fee_with_missing_cost_basis_does_not_fabricate():
    tx = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=None, value=None, fee=Decimal("0.5"), fee_asset="BNB")
    engine = AccountingEngine()
    result = engine.process([tx])
    assert result.lots[0].unit_cost is None
    assert result.lots[0].total_cost is None
    assert any(w.code == WarningCode.MISSING_COST_BASIS for w in result.warnings)


# --- P0-2: Fee must not create negative fabricated proceeds ---


def test_quote_asset_fee_with_missing_proceeds_does_not_fabricate_negative():
    tx_buy = _tx("tx-0", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"))
    tx_sell = _tx("tx-1", side=Side.SELL, quantity=Decimal("1"), price=None, value=None, fee=Decimal("10"), fee_asset="USDT")
    engine = AccountingEngine()
    result = engine.process([tx_buy, tx_sell])
    assert result.events[1].proceeds is None
    assert any(w.code == WarningCode.MISSING_PROCEEDS for w in result.warnings)


# --- P0-3: Swap acquisition falls back to disposal proceeds ---


def test_swap_acquisition_uses_disposal_proceeds_when_output_leg_missing_value():
    tx_out = _tx("tx-1", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("1"), asset="BTC", price=Decimal("50000"), value=Decimal("50000"))
    tx_in = _tx("tx-2", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("0.5"), asset="ETH", price=None, value=None)
    engine = AccountingEngine()
    result = engine.process([tx_out, tx_in])
    assert result.lots[0].unit_cost == Decimal("100000")


def test_swap_acquisition_uses_disposal_proceeds_minus_fee():
    tx_out = _tx("tx-1", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("1"), asset="BTC", price=Decimal("50000"), value=Decimal("50000"), fee=Decimal("10"), fee_asset="USDT")
    tx_in = _tx("tx-2", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("0.5"), asset="ETH", price=None, value=None, fee=Decimal("2"), fee_asset="USDT")
    engine = AccountingEngine()
    result = engine.process([tx_out, tx_in])
    assert result.lots[0].unit_cost == Decimal("99996")


# --- P0-4: Currency mismatch must not produce invalid P&L ---


def test_currency_mismatch_produces_warning_and_null_pnl():
    tx_buy = _tx("tx-0", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"), quote_asset="USDT")
    tx_sell = _tx("tx-1", side=Side.SELL, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"), quote_asset="USD")
    engine = AccountingEngine()
    result = engine.process([tx_buy, tx_sell])
    assert any(w.code == WarningCode.CURRENCY_MISMATCH for w in result.warnings)
    assert result.consumptions[0].realized_pnl is None


# --- P1-1: Duplicate transactions must not double-count ---


def test_duplicate_buy_does_not_double_count_lots():
    tx_buy1 = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"))
    tx_buy2 = _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"))
    engine = AccountingEngine()
    result = engine.process([tx_buy1, tx_buy2], unique_transaction_ids={"tx-1"})
    assert len(result.lots) == 1
    assert result.lots[0].acquired_quantity == Decimal("1")


def test_duplicate_sell_does_not_double_count_pnl():
    tx_buy = _tx("tx-0", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"))
    tx_sell1 = _tx("tx-1", side=Side.SELL, quantity=Decimal("1"), price=Decimal("60000"), value=Decimal("60000"))
    tx_sell2 = _tx("tx-1", side=Side.SELL, quantity=Decimal("1"), price=Decimal("60000"), value=Decimal("60000"))
    engine = AccountingEngine()
    result = engine.process([tx_buy, tx_sell1, tx_sell2], unique_transaction_ids={"tx-0", "tx-1"})
    assert len(result.events) == 2
    assert len(result.consumptions) == 1


# --- P1-2/P1-5: Realized PnL aggregation by currency ---


def test_realized_pnl_aggregated_by_currency():
    tx_buy_usdt = _tx("tx-0", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"), quote_asset="USDT")
    tx_sell_usdt = _tx("tx-1", side=Side.SELL, quantity=Decimal("1"), price=Decimal("60000"), value=Decimal("60000"), quote_asset="USDT")
    tx_buy_usd = _tx("tx-2", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"), quote_asset="USD")
    tx_sell_usd = _tx("tx-3", side=Side.SELL, quantity=Decimal("1"), price=Decimal("60000"), value=Decimal("60000"), quote_asset="USD")
    engine = AccountingEngine()
    result = engine.process([tx_buy_usdt, tx_sell_usdt, tx_buy_usd, tx_sell_usd])
    assert len(result.realized_pnl) == 2
    currencies = {pnl.currency for pnl in result.realized_pnl}
    assert currencies == {"USDT", "USD"}


# --- P1-3: Transfer preserves lot linkage ---


def test_matched_transfer_links_lots():
    tx_buy = _tx("tx-0", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"))
    tx_transfer = _tx("tx-1", transaction_type=TransactionType.TRANSFER, side=None, quantity=Decimal("1"), asset="BTC")
    transfer_result = type("T", (), {"matches": [type("M", (), {"source_transaction_id": "tx-1", "destination_transaction_id": "tx-2"})()]})()
    engine = AccountingEngine()
    result = engine.process([tx_buy, tx_transfer], transfer_result=transfer_result)
    transfer_event = result.events[-1]
    assert transfer_event.linked_lot_ids == [result.lots[0].lot_id]


# --- P1-4: Cross-exchange transfer matching with tx_hash ---


def test_cross_exchange_transfer_matched_with_tx_hash():
    from backend.reconciliation.transfers import TransferReconciler
    from backend.models.transaction import CanonicalTransaction
    leg_a = CanonicalTransaction(
        transaction_id="tx-1",
        source=Source.BINANCE,
        timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        transaction_type=TransactionType.TRANSFER,
        side=None,
        asset="BTC",
        quantity=Decimal("1"),
        quote_asset=None,
        price=None,
        value=None,
        fee=None,
        fee_asset=None,
        confidence=1.0,
        metadata={"source_account": "Spot", "source_operation": "Transfer Between Spot and UM Futures", "source_change_signed": "-1"},
        tx_hash="abc123",
    )
    leg_b = CanonicalTransaction(
        transaction_id="tx-2",
        source=Source.COINBASE,
        timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        transaction_type=TransactionType.TRANSFER,
        side=None,
        asset="BTC",
        quantity=Decimal("1"),
        quote_asset=None,
        price=None,
        value=None,
        fee=None,
        fee_asset=None,
        confidence=1.0,
        metadata={"source_account": "Futures", "source_operation": "Transfer Between Spot and UM Futures", "source_change_signed": "1"},
        tx_hash="abc123",
    )
    reconciler = TransferReconciler()
    result = reconciler.reconcile([leg_a, leg_b])
    assert len(result.matches) == 1
    assert result.matches[0].source_transaction_id == "tx-1"
    assert result.matches[0].destination_transaction_id == "tx-2"


# --- M023 Adversarial: Cross-Asset FIFO Isolation ---


def test_fifo_eth_disposal_does_not_consume_btc_lot():
    tx_btc_buy = _tx("tx-btc", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"), asset="BTC")
    tx_eth_sell = _tx("tx-eth", side=Side.SELL, quantity=Decimal("1"), price=Decimal("3000"), value=Decimal("3000"), asset="ETH")
    engine = AccountingEngine()
    result = engine.process([tx_btc_buy, tx_eth_sell])
    assert len(result.consumptions) == 0
    assert any(e.code == ExceptionCode.INSUFFICIENT_LOTS_FOR_DISPOSAL for e in result.errors)
    assert result.summary.total_realized_pnl is None


def test_fifo_multi_asset_interleaved_partial():
    txs = [
        _tx("btc-buy-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("40000"), value=Decimal("40000"), asset="BTC", timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)),
        _tx("eth-buy-1", side=Side.BUY, quantity=Decimal("2"), price=Decimal("2000"), value=Decimal("4000"), asset="ETH", timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)),
        _tx("btc-sell-1", side=Side.SELL, quantity=Decimal("0.5"), price=Decimal("45000"), value=Decimal("22500"), asset="BTC", timestamp=datetime(2024, 1, 2, 0, 0, 0, tzinfo=timezone.utc)),
        _tx("eth-sell-1", side=Side.SELL, quantity=Decimal("1.5"), price=Decimal("2500"), value=Decimal("3750"), asset="ETH", timestamp=datetime(2024, 1, 3, 0, 0, 0, tzinfo=timezone.utc)),
    ]
    engine = AccountingEngine()
    result = engine.process(txs)
    assert len(result.consumptions) == 2
    btc_consumptions = [c for c in result.consumptions if c.asset == "BTC"]
    eth_consumptions = [c for c in result.consumptions if c.asset == "ETH"]
    assert len(btc_consumptions) == 1
    assert len(eth_consumptions) == 1
    assert btc_consumptions[0].quantity_consumed == Decimal("0.5")
    assert eth_consumptions[0].quantity_consumed == Decimal("1.5")
    assert result.summary.total_realized_pnl == Decimal("3250")


def test_fifo_insufficient_inventory_one_asset_other_has_lots():
    txs = [
        _tx("btc-buy-1", side=Side.BUY, quantity=Decimal("2"), price=Decimal("40000"), value=Decimal("80000"), asset="BTC"),
        _tx("eth-buy-1", side=Side.BUY, quantity=Decimal("10"), price=Decimal("2000"), value=Decimal("20000"), asset="ETH"),
        _tx("btc-sell-1", side=Side.SELL, quantity=Decimal("5"), price=Decimal("50000"), value=Decimal("250000"), asset="BTC"),
        _tx("eth-sell-1", side=Side.SELL, quantity=Decimal("1"), price=Decimal("2500"), value=Decimal("2500"), asset="ETH"),
    ]
    engine = AccountingEngine()
    result = engine.process(txs)
    btc_consumptions = [c for c in result.consumptions if c.asset == "BTC"]
    eth_consumptions = [c for c in result.consumptions if c.asset == "ETH"]
    assert len(btc_consumptions) == 1
    assert len(eth_consumptions) == 1
    assert any(e.code == ExceptionCode.INSUFFICIENT_LOTS_FOR_DISPOSAL for e in result.errors)
    assert result.summary.total_realized_pnl is not None


def test_fifo_multiple_lots_per_asset_mixed_timestamps():
    txs = [
        _tx("btc-buy-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("40000"), value=Decimal("40000"), asset="BTC", timestamp=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)),
        _tx("btc-buy-2", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"), asset="BTC", timestamp=datetime(2024, 1, 3, 0, 0, 0, tzinfo=timezone.utc)),
        _tx("eth-buy-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("2000"), value=Decimal("2000"), asset="ETH", timestamp=datetime(2024, 1, 2, 0, 0, 0, tzinfo=timezone.utc)),
        _tx("eth-buy-2", side=Side.BUY, quantity=Decimal("1"), price=Decimal("2500"), value=Decimal("2500"), asset="ETH", timestamp=datetime(2024, 1, 4, 0, 0, 0, tzinfo=timezone.utc)),
        _tx("btc-sell-1", side=Side.SELL, quantity=Decimal("1.5"), price=Decimal("60000"), value=Decimal("90000"), asset="BTC", timestamp=datetime(2024, 1, 5, 0, 0, 0, tzinfo=timezone.utc)),
        _tx("eth-sell-1", side=Side.SELL, quantity=Decimal("1.5"), price=Decimal("3000"), value=Decimal("4500"), asset="ETH", timestamp=datetime(2024, 1, 6, 0, 0, 0, tzinfo=timezone.utc)),
    ]
    engine = AccountingEngine()
    result = engine.process(txs)
    btc_consumptions = [c for c in result.consumptions if c.asset == "BTC"]
    eth_consumptions = [c for c in result.consumptions if c.asset == "ETH"]
    assert len(btc_consumptions) == 2
    assert len(eth_consumptions) == 2
    btc_lot_ids = {c.lot_id for c in btc_consumptions}
    eth_lot_ids = {c.lot_id for c in eth_consumptions}
    btc_lots = {lot.lot_id for lot in result.lots if lot.asset == "BTC"}
    eth_lots = {lot.lot_id for lot in result.lots if lot.asset == "ETH"}
    assert btc_lot_ids.issubset(btc_lots)
    assert eth_lot_ids.issubset(eth_lots)


def test_fifo_swap_transfer_cross_asset():
    txs = [
        _tx("btc-buy-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("40000"), value=Decimal("40000"), asset="BTC"),
        _tx("eth-buy-1", side=Side.BUY, quantity=Decimal("2"), price=Decimal("2000"), value=Decimal("4000"), asset="ETH"),
        _tx("btc-sell-1", side=Side.SELL, quantity=Decimal("0.5"), asset="BTC", price=Decimal("50000"), value=Decimal("25000")),
        _tx("eth-sell-1", side=Side.SELL, quantity=Decimal("1"), asset="ETH", price=Decimal("2500"), value=Decimal("2500")),
        _tx("btc-transfer", transaction_type=TransactionType.TRANSFER, side=None, quantity=Decimal("0.3"), asset="BTC"),
    ]
    engine = AccountingEngine()
    result = engine.process(txs)
    btc_disposals = [e for e in result.events if e.event_type == AccountingEventType.DISPOSAL and e.asset == "BTC"]
    eth_disposals = [e for e in result.events if e.event_type == AccountingEventType.DISPOSAL and e.asset == "ETH"]
    btc_transfers = [e for e in result.events if e.event_type == AccountingEventType.TRANSFER and e.asset == "BTC"]
    assert len(btc_disposals) >= 1
    assert len(eth_disposals) >= 1
    assert len(btc_transfers) == 1


def test_fifo_duplicate_transactions_across_assets():
    txs = [
        _tx("tx-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("40000"), value=Decimal("40000"), asset="BTC"),
        _tx("tx-1-dup", side=Side.BUY, quantity=Decimal("1"), price=Decimal("40000"), value=Decimal("40000"), asset="BTC"),
        _tx("tx-2", side=Side.BUY, quantity=Decimal("2"), price=Decimal("2000"), value=Decimal("4000"), asset="ETH"),
        _tx("tx-2-dup", side=Side.BUY, quantity=Decimal("2"), price=Decimal("2000"), value=Decimal("4000"), asset="ETH"),
    ]
    engine = AccountingEngine()
    result = engine.process(txs, unique_transaction_ids={"tx-1", "tx-1-dup", "tx-2", "tx-2-dup"})
    btc_lots = [lot for lot in result.lots if lot.asset == "BTC"]
    eth_lots = [lot for lot in result.lots if lot.asset == "ETH"]
    assert len(btc_lots) == 2
    assert len(eth_lots) == 2
    assert result.summary.acquisition_events == 4


# --- M026 P2 Hardening: Currency Mismatch ---


def test_currency_mismatch_usd_cost_usdt_proceeds():
    txs = [
        _tx("buy-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"), asset="BTC", quote_asset="USD"),
        _tx("sell-1", side=Side.SELL, quantity=Decimal("1"), price=Decimal("60000"), value=Decimal("60000"), asset="BTC", quote_asset="USDT"),
    ]
    engine = AccountingEngine()
    result = engine.process(txs)
    btc_consumptions = [c for c in result.consumptions if c.asset == "BTC"]
    assert len(btc_consumptions) == 1
    assert btc_consumptions[0].realized_pnl is None
    assert any(w.code == WarningCode.CURRENCY_MISMATCH for w in result.warnings)


def test_currency_mismatch_eur_cost_usd_proceeds():
    txs = [
        _tx("buy-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"), asset="BTC", quote_asset="EUR"),
        _tx("sell-1", side=Side.SELL, quantity=Decimal("1"), price=Decimal("60000"), value=Decimal("60000"), asset="BTC", quote_asset="USD"),
    ]
    engine = AccountingEngine()
    result = engine.process(txs)
    btc_consumptions = [c for c in result.consumptions if c.asset == "BTC"]
    assert len(btc_consumptions) == 1
    assert btc_consumptions[0].realized_pnl is None
    assert any(w.code == WarningCode.CURRENCY_MISMATCH for w in result.warnings)


def test_currency_mismatch_missing_proceeds_currency():
    txs = [
        _tx("buy-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"), asset="BTC", quote_asset="USDT"),
        _tx("sell-1", side=Side.SELL, quantity=Decimal("1"), price=Decimal("60000"), value=Decimal("60000"), asset="BTC", quote_asset=None),
    ]
    engine = AccountingEngine()
    result = engine.process(txs)
    btc_consumptions = [c for c in result.consumptions if c.asset == "BTC"]
    assert len(btc_consumptions) == 1
    assert btc_consumptions[0].realized_pnl is None
    assert any(w.code == WarningCode.CURRENCY_MISMATCH for w in result.warnings)


def test_currency_mismatch_missing_cost_currency():
    txs = [
        _tx("buy-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"), asset="BTC", quote_asset=None),
        _tx("sell-1", side=Side.SELL, quantity=Decimal("1"), price=Decimal("60000"), value=Decimal("60000"), asset="BTC", quote_asset="USDT"),
    ]
    engine = AccountingEngine()
    result = engine.process(txs)
    btc_consumptions = [c for c in result.consumptions if c.asset == "BTC"]
    assert len(btc_consumptions) == 1
    assert btc_consumptions[0].realized_pnl is None
    assert any(w.code == WarningCode.CURRENCY_MISMATCH for w in result.warnings)


def test_currency_matching_no_mismatch():
    txs = [
        _tx("buy-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"), asset="BTC", quote_asset="USDT"),
        _tx("sell-1", side=Side.SELL, quantity=Decimal("1"), price=Decimal("60000"), value=Decimal("60000"), asset="BTC", quote_asset="USDT"),
    ]
    engine = AccountingEngine()
    result = engine.process(txs)
    btc_consumptions = [c for c in result.consumptions if c.asset == "BTC"]
    assert len(btc_consumptions) == 1
    assert btc_consumptions[0].realized_pnl == Decimal("10000")
    assert not any(w.code == WarningCode.CURRENCY_MISMATCH for w in result.warnings)


def test_currency_multiple_currencies_separate_aggregation():
    txs = [
        _tx("buy-1", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"), asset="BTC", quote_asset="USDT"),
        _tx("sell-1", side=Side.SELL, quantity=Decimal("1"), price=Decimal("60000"), value=Decimal("60000"), asset="BTC", quote_asset="USDT"),
        _tx("buy-2", side=Side.BUY, quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"), asset="ETH", quote_asset="USD"),
        _tx("sell-2", side=Side.SELL, quantity=Decimal("1"), price=Decimal("60000"), value=Decimal("60000"), asset="ETH", quote_asset="USD"),
    ]
    engine = AccountingEngine()
    result = engine.process(txs)
    assert len(result.realized_pnl) == 2
    currencies = {pnl.currency for pnl in result.realized_pnl}
    assert currencies == {"USDT", "USD"}


# --- M026 P2 Hardening: Swap Fee ---


def test_swap_excessive_base_asset_fee_preserves_cost_basis():
    txs = [
        _tx("swap-out", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("1"), asset="BTC", price=Decimal("50000"), value=Decimal("50000")),
        _tx("swap-in", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("0.5"), asset="ETH", price=None, value=None, fee=Decimal("0.6"), fee_asset="ETH"),
    ]
    engine = AccountingEngine()
    result = engine.process(txs)
    eth_acquisitions = [e for e in result.events if e.event_type == AccountingEventType.ACQUISITION and e.asset == "ETH"]
    assert len(eth_acquisitions) == 1
    assert eth_acquisitions[0].cost_basis == Decimal("50000")
    assert any(w.code == WarningCode.THIRD_ASSET_FEE for w in result.warnings)


def test_swap_base_asset_fee_equal_to_quantity():
    txs = [
        _tx("swap-out", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("1"), asset="BTC", price=Decimal("50000"), value=Decimal("50000")),
        _tx("swap-in", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("0.5"), asset="ETH", price=None, value=None, fee=Decimal("0.5"), fee_asset="ETH"),
    ]
    engine = AccountingEngine()
    result = engine.process(txs)
    eth_acquisitions = [e for e in result.events if e.event_type == AccountingEventType.ACQUISITION and e.asset == "ETH"]
    assert len(eth_acquisitions) == 1
    assert eth_acquisitions[0].cost_basis == Decimal("50000")


def test_swap_normal_base_asset_fee():
    txs = [
        _tx("swap-out", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("1"), asset="BTC", price=Decimal("50000"), value=Decimal("50000")),
        _tx("swap-in", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("0.5"), asset="ETH", price=None, value=None, fee=Decimal("0.1"), fee_asset="ETH"),
    ]
    engine = AccountingEngine()
    result = engine.process(txs)
    eth_acquisitions = [e for e in result.events if e.event_type == AccountingEventType.ACQUISITION and e.asset == "ETH"]
    assert len(eth_acquisitions) == 1
    assert eth_acquisitions[0].cost_basis == Decimal("50000")


def test_swap_third_asset_fee():
    txs = [
        _tx("swap-out", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("1"), asset="BTC", price=Decimal("50000"), value=Decimal("50000")),
        _tx("swap-in", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("0.5"), asset="ETH", price=None, value=None, fee=Decimal("10"), fee_asset="BTC"),
    ]
    engine = AccountingEngine()
    result = engine.process(txs)
    eth_acquisitions = [e for e in result.events if e.event_type == AccountingEventType.ACQUISITION and e.asset == "ETH"]
    assert len(eth_acquisitions) == 1
    assert eth_acquisitions[0].cost_basis == Decimal("50000")


# --- M026 P2 Hardening: Swap Direct-Pair ---


def test_swap_three_transactions_greedy_pairing():
    ts = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    txs = [
        _tx("swap-out-1", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("1"), asset="BTC", price=Decimal("50000"), value=Decimal("50000"), timestamp=ts),
        _tx("swap-in-1", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("0.5"), asset="ETH", price=Decimal("1000"), value=Decimal("500"), timestamp=ts),
        _tx("swap-out-2", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("1"), asset="SOL", price=Decimal("100"), value=Decimal("100"), timestamp=ts),
    ]
    engine = AccountingEngine()
    result = engine.process(txs)
    disposals = [e for e in result.events if e.event_type == AccountingEventType.DISPOSAL]
    acquisitions = [e for e in result.events if e.event_type == AccountingEventType.ACQUISITION]
    assert len(disposals) == 1
    assert len(acquisitions) == 1
    assert any(w.code == WarningCode.PARTIAL_SWAP_VALUATION for w in result.warnings)


def test_swap_four_transactions_two_pairs():
    ts = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    txs = [
        _tx("swap-out-1", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("1"), asset="BTC", price=Decimal("50000"), value=Decimal("50000"), timestamp=ts),
        _tx("swap-in-1", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("0.5"), asset="ETH", price=Decimal("1000"), value=Decimal("500"), timestamp=ts),
        _tx("swap-out-2", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("1"), asset="SOL", price=Decimal("100"), value=Decimal("100"), timestamp=ts),
        _tx("swap-in-2", transaction_type=TransactionType.SWAP, side=None, quantity=Decimal("10"), asset="ADA", price=Decimal("1"), value=Decimal("10"), timestamp=ts),
    ]
    engine = AccountingEngine()
    result = engine.process(txs)
    disposals = [e for e in result.events if e.event_type == AccountingEventType.DISPOSAL]
    acquisitions = [e for e in result.events if e.event_type == AccountingEventType.ACQUISITION]
    assert len(disposals) == 2
    assert len(acquisitions) == 2
