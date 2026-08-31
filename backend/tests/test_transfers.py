from datetime import datetime, timezone
from decimal import Decimal

from backend.models.transaction import (
    CanonicalTransaction,
    Side,
    Source,
    TransactionType,
)
from backend.reconciliation.transfers import (
    TransferClassification,
    TransferReconciler,
    TransferResult,
)


def _transfer_tx(
    tid,
    account,
    operation,
    asset,
    signed_change,
    timestamp,
    source=Source.BINANCE,
):
    return CanonicalTransaction(
        transaction_id=tid,
        source=source,
        timestamp=timestamp,
        transaction_type=TransactionType.TRANSFER,
        asset=asset,
        quantity=abs(Decimal(str(signed_change))),
        confidence=1.0,
        metadata={
            "source_account": account,
            "source_operation": operation,
            "source_change_signed": str(signed_change),
        },
    )


def _ts(second: int) -> datetime:
    return datetime(2024, 1, 1, 12, 0, second, tzinfo=timezone.utc)


def _reconcile(*txs) -> TransferResult:
    return TransferReconciler().reconcile(list(txs))


# --- Directional matches ---

def test_spot_to_futures():
    a = _transfer_tx("a", "Spot", "Transfer Between Spot and UM Futures", "USDT", "-1.90294738", _ts(0))
    b = _transfer_tx("b", "USD-M Futures", "Transfer Between Spot and UM Futures", "USDT", "1.90294738", _ts(0))
    res = _reconcile(a, b)
    assert len(res.matches) == 1
    m = res.matches[0]
    assert m.source_account == "Spot"
    assert m.destination_account == "USD-M Futures"
    assert m.quantity == Decimal("1.90294738")


def test_futures_to_spot():
    a = _transfer_tx("a", "USD-M Futures", "Transfer Between Spot and UM Futures", "USDT", "-1.90294738", _ts(0))
    b = _transfer_tx("b", "Spot", "Transfer Between Spot and UM Futures", "USDT", "1.90294738", _ts(0))
    res = _reconcile(a, b)
    assert len(res.matches) == 1
    assert res.matches[0].source_account == "USD-M Futures"
    assert res.matches[0].destination_account == "Spot"


def test_futures_to_funding():
    a = _transfer_tx("a", "USD-M Futures", "Transfer Between UM Futures and Funding", "USDT", "-1.90983349", _ts(0))
    b = _transfer_tx("b", "Funding", "Transfer Between UM Futures and Funding", "USDT", "1.90983349", _ts(0))
    res = _reconcile(a, b)
    assert len(res.matches) == 1
    assert res.matches[0].source_account == "USD-M Futures"
    assert res.matches[0].destination_account == "Funding"


def test_funding_to_futures():
    a = _transfer_tx("a", "Funding", "Transfer Between UM Futures and Funding", "USDT", "-1.90983349", _ts(0))
    b = _transfer_tx("b", "USD-M Futures", "Transfer Between UM Futures and Funding", "USDT", "1.90983349", _ts(0))
    res = _reconcile(a, b)
    assert len(res.matches) == 1
    assert res.matches[0].source_account == "Funding"


def test_spot_to_funding():
    a = _transfer_tx("a", "Spot", "Transfer Between Spot and Funding", "USDT", "-1.90294738", _ts(0))
    b = _transfer_tx("b", "Funding", "Transfer Between Spot and Funding", "USDT", "1.90294738", _ts(0))
    res = _reconcile(a, b)
    assert len(res.matches) == 1
    assert res.matches[0].destination_account == "Funding"


def test_funding_to_spot():
    a = _transfer_tx("a", "Funding", "Transfer Between Spot and Funding", "USDT", "-1.90294738", _ts(0))
    b = _transfer_tx("b", "Spot", "Transfer Between Spot and Funding", "USDT", "1.90294738", _ts(0))
    res = _reconcile(a, b)
    assert len(res.matches) == 1
    assert res.matches[0].source_account == "Funding"


# --- Timestamp behavior ---

def test_exact_timestamp():
    a = _transfer_tx("a", "Spot", "Transfer Between Spot and UM Futures", "USDT", "-100", _ts(0))
    b = _transfer_tx("b", "USD-M Futures", "Transfer Between Spot and UM Futures", "USDT", "100", _ts(0))
    res = _reconcile(a, b)
    assert res.matches[0].confidence == 100


def test_timestamp_within_tolerance():
    a = _transfer_tx("a", "Spot", "Transfer Between Spot and UM Futures", "USDT", "-100", _ts(0))
    b = _transfer_tx("b", "USD-M Futures", "Transfer Between Spot and UM Futures", "USDT", "100", _ts(1))
    res = _reconcile(a, b)
    assert len(res.matches) == 1
    assert res.matches[0].confidence == 95


def test_timestamp_outside_tolerance():
    a = _transfer_tx("a", "Spot", "Transfer Between Spot and UM Futures", "USDT", "-100", _ts(0))
    b = _transfer_tx("b", "USD-M Futures", "Transfer Between Spot and UM Futures", "USDT", "100", _ts(5))
    res = _reconcile(a, b)
    assert len(res.matches) == 0


# --- Quantity / asset ---

def test_equal_quantity_match():
    a = _transfer_tx("a", "Spot", "Transfer Between Spot and UM Futures", "USDT", "-100", _ts(0))
    b = _transfer_tx("b", "USD-M Futures", "Transfer Between Spot and UM Futures", "USDT", "100", _ts(0))
    assert len(_reconcile(a, b).matches) == 1


def test_unequal_quantity_no_match():
    a = _transfer_tx("a", "Spot", "Transfer Between Spot and UM Futures", "USDT", "-100", _ts(0))
    b = _transfer_tx("b", "USD-M Futures", "Transfer Between Spot and UM Futures", "USDT", "99", _ts(0))
    assert len(_reconcile(a, b).matches) == 0


def test_different_asset_no_match():
    a = _transfer_tx("a", "Spot", "Transfer Between Spot and UM Futures", "USDT", "-100", _ts(0))
    b = _transfer_tx("b", "USD-M Futures", "Transfer Between Spot and UM Futures", "USDC", "100", _ts(0))
    assert len(_reconcile(a, b).matches) == 0


# --- Sign handling ---

def test_opposite_signs_match():
    a = _transfer_tx("a", "Spot", "Transfer Between Spot and UM Futures", "USDT", "-100", _ts(0))
    b = _transfer_tx("b", "USD-M Futures", "Transfer Between Spot and UM Futures", "USDT", "100", _ts(0))
    assert len(_reconcile(a, b).matches) == 1


def test_same_signs_no_match():
    a = _transfer_tx("a", "Spot", "Transfer Between Spot and UM Futures", "USDT", "-100", _ts(0))
    b = _transfer_tx("b", "USD-M Futures", "Transfer Between Spot and UM Futures", "USDT", "-100", _ts(0))
    assert len(_reconcile(a, b).matches) == 0


def test_same_account_no_match():
    a = _transfer_tx("a", "Spot", "Transfer Between Spot and UM Futures", "USDT", "-100", _ts(0))
    b = _transfer_tx("b", "Spot", "Transfer Between Spot and UM Futures", "USDT", "100", _ts(0))
    assert len(_reconcile(a, b).matches) == 0


# --- Non-transfer transaction types ---

def test_trade_vs_transfer_no_match():
    trade = CanonicalTransaction(
        transaction_id="t1",
        source=Source.BINANCE,
        timestamp=_ts(0),
        transaction_type=TransactionType.TRADE,
        side=Side.BUY,
        asset="USDT",
        quantity=Decimal("100"),
        confidence=1.0,
        metadata={"source_account": "Spot", "source_operation": "Buy", "source_change_signed": "100"},
    )
    transfer = _transfer_tx("t2", "USD-M Futures", "Transfer Between Spot and UM Futures", "USDT", "100", _ts(0))
    assert len(_reconcile(trade, transfer).matches) == 0


def test_deposit_vs_transfer_no_match():
    deposit = CanonicalTransaction(
        transaction_id="d1",
        source=Source.BINANCE,
        timestamp=_ts(0),
        transaction_type=TransactionType.DEPOSIT,
        asset="USDT",
        quantity=Decimal("100"),
        confidence=1.0,
        metadata={"source_account": "Spot", "source_operation": "Deposit", "source_change_signed": "100"},
    )
    transfer = _transfer_tx("d2", "USD-M Futures", "Transfer Between Spot and UM Futures", "USDT", "100", _ts(0))
    assert len(_reconcile(deposit, transfer).matches) == 0


def test_two_deposits_no_match():
    a = CanonicalTransaction(
        transaction_id="d1",
        source=Source.BINANCE,
        timestamp=_ts(0),
        transaction_type=TransactionType.DEPOSIT,
        asset="USDT",
        quantity=Decimal("100"),
        confidence=1.0,
        metadata={"source_account": "Spot", "source_operation": "Deposit", "source_change_signed": "100"},
    )
    b = CanonicalTransaction(
        transaction_id="d2",
        source=Source.BINANCE,
        timestamp=_ts(0),
        transaction_type=TransactionType.DEPOSIT,
        asset="USDT",
        quantity=Decimal("100"),
        confidence=1.0,
        metadata={"source_account": "Funding", "source_operation": "Deposit", "source_change_signed": "100"},
    )
    assert len(_reconcile(a, b).matches) == 0


def test_two_withdrawals_no_match():
    a = CanonicalTransaction(
        transaction_id="w1",
        source=Source.BINANCE,
        timestamp=_ts(0),
        transaction_type=TransactionType.WITHDRAWAL,
        asset="USDT",
        quantity=Decimal("100"),
        confidence=1.0,
        metadata={"source_account": "Spot", "source_operation": "Withdraw", "source_change_signed": "-100"},
    )
    b = CanonicalTransaction(
        transaction_id="w2",
        source=Source.BINANCE,
        timestamp=_ts(0),
        transaction_type=TransactionType.WITHDRAWAL,
        asset="USDT",
        quantity=Decimal("100"),
        confidence=1.0,
        metadata={"source_account": "Funding", "source_operation": "Withdraw", "source_change_signed": "-100"},
    )
    assert len(_reconcile(a, b).matches) == 0


# --- Cross-exchange / unrelated ---

def test_cross_exchange_no_match():
    a = _transfer_tx("a", "Spot", "Transfer Between Spot and UM Futures", "USDT", "-100", _ts(0), source=Source.BINANCE)
    b = _transfer_tx("b", "USD-M Futures", "Transfer Between Spot and UM Futures", "USDT", "100", _ts(0), source=Source.COINBASE)
    assert len(_reconcile(a, b).matches) == 0


def test_two_unrelated_transfers():
    a = _transfer_tx("a", "Spot", "Transfer Between Spot and UM Futures", "USDT", "-100", _ts(0))
    b = _transfer_tx("b", "USD-M Futures", "Transfer Between Spot and UM Futures", "USDT", "100", _ts(0))
    c = _transfer_tx("c", "Spot", "Transfer Between Spot and UM Futures", "USDT", "-100", _ts(10))
    d = _transfer_tx("d", "USD-M Futures", "Transfer Between Spot and UM Futures", "USDT", "100", _ts(10))
    res = _reconcile(a, b, c, d)
    assert len(res.matches) == 2


# --- Determinism / auditability ---

def test_deterministic_transfer_id():
    a = _transfer_tx("a", "Spot", "Transfer Between Spot and UM Futures", "USDT", "-1.90294738", _ts(0))
    b = _transfer_tx("b", "USD-M Futures", "Transfer Between Spot and UM Futures", "USDT", "1.90294738", _ts(0))
    id1 = _reconcile(a, b).matches[0].transfer_id
    id2 = _reconcile(a, b).matches[0].transfer_id
    assert id1 == id2


def test_transfer_id_independent_of_leg_order():
    a = _transfer_tx("a", "Spot", "Transfer Between Spot and UM Futures", "USDT", "-1.90294738", _ts(0))
    b = _transfer_tx("b", "USD-M Futures", "Transfer Between Spot and UM Futures", "USDT", "1.90294738", _ts(0))
    id_forward = _reconcile(a, b).matches[0].transfer_id
    id_backward = _reconcile(b, a).matches[0].transfer_id
    assert id_forward == id_backward


def test_no_source_deletion():
    a = _transfer_tx("a", "Spot", "Transfer Between Spot and UM Futures", "USDT", "-100", _ts(0))
    b = _transfer_tx("b", "USD-M Futures", "Transfer Between Spot and UM Futures", "USDT", "100", _ts(0))
    res = _reconcile(a, b)
    all_ids = [m.source_transaction_id for m in res.matches] + [
        m.destination_transaction_id for m in res.matches
    ] + res.unmatched_leg_ids
    assert set(all_ids) == {"a", "b"}


def test_audit_reasons_present():
    a = _transfer_tx("a", "Spot", "Transfer Between Spot and UM Futures", "USDT", "-100", _ts(0))
    b = _transfer_tx("b", "USD-M Futures", "Transfer Between Spot and UM Futures", "USDT", "100", _ts(0))
    reasons = _reconcile(a, b).matches[0].reasons
    assert any("opposite" in r.lower() for r in reasons)
    assert any("compatible" in r.lower() for r in reasons)
