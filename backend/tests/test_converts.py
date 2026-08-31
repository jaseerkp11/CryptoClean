from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend.models.transaction import CanonicalTransaction, Source, TransactionType
from backend.processing.pipeline import ProcessingPipeline
from backend.processing.models import ProcessingResult
from backend.reconciliation.converts import ConvertReconciler, ConvertResult


def _convert_leg(tid, account, asset, signed_change, timestamp, source=Source.BINANCE, metadata=None):
    if metadata is None:
        metadata = {
            "source_account": account,
            "source_operation": "Binance Convert",
            "source_change_signed": str(signed_change),
        }
    return CanonicalTransaction(
        transaction_id=tid,
        source=source,
        timestamp=timestamp,
        transaction_type=TransactionType.UNKNOWN,
        asset=asset,
        quantity=abs(Decimal(str(signed_change))),
        confidence=1.0,
        metadata=metadata,
    )


def _ts(second: int) -> datetime:
    return datetime(2024, 10, 20, 21, 0, second, tzinfo=timezone.utc)


def _reconcile(*txs) -> ConvertResult:
    return ConvertReconciler().reconcile(list(txs))


# --- Simple converts ---

def test_simple_sol_to_usdt():
    a = _convert_leg("a", "Spot", "SOL", "-0.0215519", _ts(0))
    b = _convert_leg("b", "Spot", "USDT", "3.42578053", _ts(0))
    res = _reconcile(a, b)
    assert len(res.matches) == 1
    m = res.matches[0]
    assert m.input_asset == "SOL"
    assert m.input_quantity == Decimal("0.0215519")
    assert m.output_asset == "USDT"
    assert m.output_quantity == Decimal("3.42578053")
    assert m.confidence == 100


def test_usdt_to_btc():
    a = _convert_leg("a", "Spot", "USDT", "-100", _ts(0))
    b = _convert_leg("b", "Spot", "BTC", "0.001", _ts(0))
    res = _reconcile(a, b)
    assert len(res.matches) == 1
    assert res.matches[0].input_asset == "USDT"
    assert res.matches[0].output_asset == "BTC"


def test_btc_to_eth():
    a = _convert_leg("a", "Spot", "BTC", "-0.01", _ts(0))
    b = _convert_leg("b", "Spot", "ETH", "0.15", _ts(0))
    res = _reconcile(a, b)
    assert len(res.matches) == 1
    assert res.matches[0].input_asset == "BTC"
    assert res.matches[0].output_asset == "ETH"


# --- Timestamp behavior ---

def test_exact_timestamp():
    a = _convert_leg("a", "Spot", "SOL", "-1", _ts(0))
    b = _convert_leg("b", "Spot", "USDT", "10", _ts(0))
    res = _reconcile(a, b)
    assert res.matches[0].confidence == 100


def test_timestamp_within_tolerance():
    a = _convert_leg("a", "Spot", "SOL", "-1", _ts(0))
    b = _convert_leg("b", "Spot", "USDT", "10", _ts(1))
    res = _reconcile(a, b)
    assert len(res.matches) == 1
    assert res.matches[0].confidence == 95


def test_timestamp_outside_tolerance():
    a = _convert_leg("a", "Spot", "SOL", "-1", _ts(0))
    b = _convert_leg("b", "Spot", "USDT", "10", _ts(5))
    res = _reconcile(a, b)
    assert len(res.matches) == 0


# --- Sign handling ---

def test_positive_negative_legs_match():
    a = _convert_leg("a", "Spot", "SOL", "-1", _ts(0))
    b = _convert_leg("b", "Spot", "USDT", "10", _ts(0))
    assert len(_reconcile(a, b).matches) == 1


def test_two_positive_legs_rejected():
    a = _convert_leg("a", "Spot", "SOL", "1", _ts(0))
    b = _convert_leg("b", "Spot", "USDT", "10", _ts(0))
    assert len(_reconcile(a, b).matches) == 0


def test_two_negative_legs_rejected():
    a = _convert_leg("a", "Spot", "SOL", "-1", _ts(0))
    b = _convert_leg("b", "Spot", "USDT", "-10", _ts(0))
    assert len(_reconcile(a, b).matches) == 0


# --- Asset / account / source ---

def test_same_asset_rejected():
    a = _convert_leg("a", "Spot", "USDT", "-10", _ts(0))
    b = _convert_leg("b", "Spot", "USDT", "10", _ts(0))
    assert len(_reconcile(a, b).matches) == 0


def test_different_account_rejected():
    a = _convert_leg("a", "Spot", "SOL", "-1", _ts(0))
    b = _convert_leg("b", "USD-M Futures", "USDT", "10", _ts(0))
    assert len(_reconcile(a, b).matches) == 0


def test_different_source_rejected():
    a = _convert_leg("a", "Spot", "SOL", "-1", _ts(0), source=Source.BINANCE)
    b = _convert_leg("b", "Spot", "USDT", "10", _ts(0), source=Source.COINBASE)
    assert len(_reconcile(a, b).matches) == 0


# --- Non-convert operations ---

def test_convert_plus_fee_not_grouped():
    convert = _convert_leg("c", "Spot", "SOL", "-1", _ts(0))
    fee = CanonicalTransaction(
        transaction_id="f",
        source=Source.BINANCE,
        timestamp=_ts(0),
        transaction_type=TransactionType.FEE,
        asset="USDT",
        quantity=Decimal("0.1"),
        confidence=1.0,
        metadata={"source_account": "Spot", "source_operation": "Fee", "source_change_signed": "-0.1"},
    )
    assert len(_reconcile(convert, fee).matches) == 0


def test_convert_plus_transfer_not_grouped():
    convert = _convert_leg("c", "Spot", "SOL", "-1", _ts(0))
    transfer = CanonicalTransaction(
        transaction_id="t",
        source=Source.BINANCE,
        timestamp=_ts(0),
        transaction_type=TransactionType.TRANSFER,
        asset="USDT",
        quantity=Decimal("10"),
        confidence=1.0,
        metadata={"source_account": "Spot", "source_operation": "Transfer Between Spot and UM Futures", "source_change_signed": "10"},
    )
    assert len(_reconcile(convert, transfer).matches) == 0


# --- Ambiguity ---

def test_ambiguous_candidates_handled():
    # Two negative SOL legs and one positive USDT leg -> ambiguous, no match.
    a = _convert_leg("a", "Spot", "SOL", "-1", _ts(0))
    b = _convert_leg("b", "Spot", "SOL", "-2", _ts(0))
    c = _convert_leg("c", "Spot", "USDT", "10", _ts(0))
    res = _reconcile(a, b, c)
    assert len(res.matches) == 0
    assert any("ambiguous" in w.lower() for w in res.warnings)


# --- Edge cases ---

def test_zero_change_rejected():
    a = _convert_leg("a", "Spot", "SOL", "0.0001", _ts(0))
    b = _convert_leg("b", "Spot", "USDT", "10", _ts(0))
    assert len(_reconcile(a, b).matches) == 0


def test_invalid_decimal_handled():
    # Invalid Decimal in signed_change should be skipped safely.
    tx = CanonicalTransaction(
        transaction_id="bad",
        source=Source.BINANCE,
        timestamp=_ts(0),
        transaction_type=TransactionType.UNKNOWN,
        asset="SOL",
        quantity=Decimal("1"),
        confidence=1.0,
        metadata={"source_account": "Spot", "source_operation": "Binance Convert", "source_change_signed": "not-a-number"},
    )
    res = _reconcile(tx)
    assert len(res.matches) == 0
    assert len(res.unresolved_leg_ids) == 0


# --- Determinism / auditability ---

def test_deterministic_convert_id():
    a = _convert_leg("a", "Spot", "SOL", "-1", _ts(0))
    b = _convert_leg("b", "Spot", "USDT", "10", _ts(0))
    id1 = _reconcile(a, b).matches[0].convert_id
    id2 = _reconcile(a, b).matches[0].convert_id
    assert id1 == id2


def test_convert_id_independent_of_leg_order():
    a = _convert_leg("a", "Spot", "SOL", "-1", _ts(0))
    b = _convert_leg("b", "Spot", "USDT", "10", _ts(0))
    forward = _reconcile(a, b).matches[0].convert_id
    backward = _reconcile(b, a).matches[0].convert_id
    assert forward == backward


def test_original_transactions_preserved():
    a = _convert_leg("a", "Spot", "SOL", "-1", _ts(0))
    b = _convert_leg("b", "Spot", "USDT", "10", _ts(0))
    res = _reconcile(a, b)
    all_ids = [m.input_transaction_id for m in res.matches] + [
        m.output_transaction_id for m in res.matches
    ] + res.unresolved_leg_ids
    assert set(all_ids) == {"a", "b"}


def test_user_id_not_in_findings():
    a = _convert_leg("a", "Spot", "SOL", "-1", _ts(0), metadata={"User ID": "12345"})
    b = _convert_leg("b", "Spot", "USDT", "10", _ts(0))
    res = _reconcile(a, b)
    assert "12345" not in str(res)


def test_user_id_not_stored_in_metadata():
    a = _convert_leg("a", "Spot", "SOL", "-1", _ts(0), metadata={"User ID": "12345"})
    b = _convert_leg("b", "Spot", "USDT", "10", _ts(0))
    res = _reconcile(a, b)
    for m in res.matches:
        assert "User ID" not in str(m)


# --- Pipeline integration ---

def test_pipeline_returns_convert_matches():
    csv = (
        "User ID,Time,Account,Operation,Coin,Change,Remark\n"
        "REDACTED,2024-10-20 21:09:28,Spot,Binance Convert,USDT,3.42578053\n"
        "REDACTED,2024-10-20 21:09:28,Spot,Binance Convert,SOL,-0.0215519\n"
    )
    res = ProcessingPipeline().process_csv_content(csv, "UTC")
    assert res.convert_matches is not None
    assert len(res.convert_matches.matches) == 1
    assert res.convert_matches.matches[0].input_asset == "SOL"
    assert res.convert_matches.matches[0].output_asset == "USDT"


def test_summary_convert_count():
    csv = (
        "User ID,Time,Account,Operation,Coin,Change,Remark\n"
        "REDACTED,2024-10-20 21:09:28,Spot,Binance Convert,USDT,3.42578053\n"
        "REDACTED,2024-10-20 21:09:28,Spot,Binance Convert,SOL,-0.0215519\n"
    )
    res = ProcessingPipeline().process_csv_content(csv, "UTC")
    assert res.summary.convert_events == 1


def test_unresolved_rows_produce_warnings():
    # Three positive legs -> ambiguous, unresolved.
    csv = (
        "User ID,Time,Account,Operation,Coin,Change,Remark\n"
        "REDACTED,2024-10-20 21:09:28,Spot,Binance Convert,USDT,3.42578053\n"
        "REDACTED,2024-10-20 21:09:28,Spot,Binance Convert,USDT,2.0\n"
        "REDACTED,2024-10-20 21:09:28,Spot,Binance Convert,BTC,0.001\n"
    )
    res = ProcessingPipeline().process_csv_content(csv, "UTC")
    assert res.summary.unresolved_convert_rows == 3
    assert any("ambiguous" in w.lower() for w in res.warnings)
