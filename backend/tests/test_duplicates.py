from datetime import datetime, timezone, timedelta
from decimal import Decimal

from backend.models.transaction import (
    CanonicalTransaction,
    Side,
    Source,
    TransactionType,
)
from backend.reconciliation.duplicates import (
    DuplicateClassification,
    DuplicateDetector,
)


def _tx(
    transaction_id,
    source=Source.BINANCE,
    timestamp=None,
    transaction_type=TransactionType.DEPOSIT,
    side=None,
    asset="BTC",
    quantity=Decimal("1"),
    quote_asset=None,
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
        value=value,
        fee=fee,
        fee_asset=fee_asset,
        wallet=wallet,
        counterparty=counterparty,
        tx_hash=tx_hash,
        confidence=1.0,
        metadata=metadata,
    )


def test_exact_same_transaction_id():
    a = _tx("id-1", asset="BTC", quantity=Decimal("1"))
    b = _tx("id-1", asset="BTC", quantity=Decimal("1"))
    result = DuplicateDetector().detect([a, b])
    assert len(result.groups) == 1
    assert result.groups[0].classification == DuplicateClassification.EXACT_DUPLICATE
    assert len(result.groups[0].transaction_ids) == 2


def test_same_source_transaction_id():
    a = _tx("a", source_transaction_id="TID-1")
    b = _tx("b", source_transaction_id="TID-1")
    result = DuplicateDetector().detect([a, b])
    assert len(result.groups) == 1
    assert result.groups[0].score >= 70
    assert result.groups[0].classification != DuplicateClassification.UNIQUE


def test_same_tx_hash():
    a = _tx("a", tx_hash="0xabc")
    b = _tx("b", tx_hash="0xabc")
    result = DuplicateDetector().detect([a, b])
    assert len(result.groups) == 1
    assert result.groups[0].score >= 70
    assert "same tx_hash" in result.groups[0].reasons


def test_same_transaction_fields_timestamp():
    a = _tx(
        "a",
        transaction_type=TransactionType.DEPOSIT,
        asset="USDT",
        quantity=Decimal("100"),
        wallet="w1",
        counterparty="cp",
        quote_asset="USD",
        value=Decimal("100"),
        fee=Decimal("0.1"),
        fee_asset="USDT",
    )
    b = _tx(
        "b",
        transaction_type=TransactionType.DEPOSIT,
        asset="USDT",
        quantity=Decimal("100"),
        wallet="w1",
        counterparty="cp",
        quote_asset="USD",
        value=Decimal("100"),
        fee=Decimal("0.1"),
        fee_asset="USDT",
    )
    result = DuplicateDetector().detect([a, b])
    assert len(result.groups) == 1
    assert result.groups[0].classification != DuplicateClassification.UNIQUE


def test_timestamp_within_tolerance():
    base = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    a = _tx("a", timestamp=base, asset="USDT", quantity=Decimal("1"))
    b = _tx(
        "b",
        timestamp=base.replace(microsecond=500000),
        asset="USDT",
        quantity=Decimal("1"),
    )
    result = DuplicateDetector(timestamp_tolerance_seconds=1).detect([a, b])
    assert len(result.groups) == 1


def test_timestamp_outside_tolerance():
    base = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    a = _tx("a", timestamp=base, asset="USDT", quantity=Decimal("1"))
    b = _tx(
        "b",
        timestamp=base.replace(second=5),
        asset="USDT",
        quantity=Decimal("1"),
    )
    result = DuplicateDetector(timestamp_tolerance_seconds=1).detect([a, b])
    assert len(result.groups) == 0
    assert "b" in result.unique_transaction_ids


def test_different_quantity():
    a = _tx("a", asset="USDT", quantity=Decimal("100"))
    b = _tx("b", asset="USDT", quantity=Decimal("200"))
    result = DuplicateDetector().detect([a, b])
    assert len(result.groups) == 0


def test_different_asset():
    a = _tx("a", asset="BTC", quantity=Decimal("1"))
    b = _tx("b", asset="ETH", quantity=Decimal("1"))
    result = DuplicateDetector().detect([a, b])
    assert len(result.groups) == 0


def test_same_amount_alone_not_duplicate():
    base = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    a = _tx(
        "a",
        timestamp=base,
        transaction_type=TransactionType.DEPOSIT,
        asset="USDT",
        quantity=Decimal("100"),
    )
    b = _tx(
        "b",
        timestamp=base.replace(day=2),
        transaction_type=TransactionType.WITHDRAWAL,
        asset="USDT",
        quantity=Decimal("100"),
    )
    result = DuplicateDetector().detect([a, b])
    assert len(result.groups) == 0


def test_cross_source_not_automatic_duplicate():
    base = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    a = _tx("a", source=Source.BINANCE, timestamp=base, asset="USDT", quantity=Decimal("100"))
    b = _tx("b", source=Source.COINBASE, timestamp=base, asset="USDT", quantity=Decimal("100"))
    result = DuplicateDetector().detect([a, b])
    assert len(result.groups) == 0


def test_opposite_transfer_legs_not_duplicates():
    base = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    a = _tx(
        "a",
        transaction_type=TransactionType.TRANSFER,
        asset="USDT",
        quantity=Decimal("1.90294738"),
        wallet="Spot",
        metadata={"source_change_signed": "-1.90294738"},
    )
    b = _tx(
        "b",
        transaction_type=TransactionType.TRANSFER,
        asset="USDT",
        quantity=Decimal("1.90294738"),
        wallet="Futures",
        metadata={"source_change_signed": "1.90294738"},
    )
    result = DuplicateDetector().detect([a, b])
    assert len(result.groups) == 0


def test_decimal_precision_preserved():
    a = _tx("a", asset="X", quantity=Decimal("0.0215519"))
    b = _tx("b", asset="X", quantity=Decimal("0.0215519"))
    result = DuplicateDetector().detect([a, b])
    assert len(result.groups) == 1
    # Decimal equality (not float) is what matched the quantity.
    assert any("same quantity" in r for r in result.groups[0].reasons)


def test_user_id_never_used():
    a = _tx("a", asset="USDT", quantity=Decimal("100"), metadata={"User ID": "12345"})
    b = _tx("b", asset="USDT", quantity=Decimal("100"), metadata={"User ID": "99999"})
    result = DuplicateDetector().detect([a, b])
    # Metadata is ignored; the pair still groups on real fields only.
    assert len(result.groups) == 1


def test_metadata_difference_does_not_prevent_detection():
    a = _tx("a", asset="USDT", quantity=Decimal("100"), metadata={"note": "alpha"})
    b = _tx("b", asset="USDT", quantity=Decimal("100"), metadata={"note": "beta"})
    result = DuplicateDetector().detect([a, b])
    assert len(result.groups) == 1


def test_duplicate_groups_abc():
    base = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    a = _tx("a", timestamp=base, asset="USDT", quantity=Decimal("100"))
    b = _tx("b", timestamp=base, asset="USDT", quantity=Decimal("100"))
    c = _tx("c", timestamp=base, asset="USDT", quantity=Decimal("100"))
    result = DuplicateDetector().detect([a, b, c])
    # All three should be in a single connected group.
    grouped_ids = [tid for g in result.groups for tid in g.transaction_ids]
    assert set(grouped_ids) == {"a", "b", "c"}


def test_unique_remains_unique():
    a = _tx("a", asset="BTC", quantity=Decimal("1"))
    result = DuplicateDetector().detect([a])
    assert len(result.groups) == 0
    assert "a" in result.unique_transaction_ids


def test_no_transaction_deleted():
    a = _tx("a", asset="USDT", quantity=Decimal("100"))
    b = _tx("b", asset="USDT", quantity=Decimal("100"))
    c = _tx("c", asset="BTC", quantity=Decimal("1"))
    result = DuplicateDetector().detect([a, b, c])
    all_ids = [tid for g in result.groups for tid in g.transaction_ids]
    all_ids += result.unique_transaction_ids
    assert set(all_ids) == {"a", "b", "c"}


def test_duplicate_detection_scalability_many_same_asset_transactions():
    from zoneinfo import ZoneInfo

    base = datetime(2024, 1, 1, 12, 0, 0, tzinfo=ZoneInfo("UTC"))
    transactions = []
    for i in range(10000):
        tx = _tx(
            f"tx_{i}",
            timestamp=base + timedelta(seconds=i * 2),
            asset="BTC",
            quantity=Decimal("0.01"),
        )
        transactions.append(tx)

    detector = DuplicateDetector(timestamp_tolerance_seconds=1)
    original_score_pair = detector._score_pair
    call_count = 0

    def counting_score_pair(a, b):
        nonlocal call_count
        call_count += 1
        return original_score_pair(a, b)

    detector._score_pair = counting_score_pair
    result = detector.detect(transactions)

    assert call_count < 50000, f"Too many pair comparisons: {call_count}"
    assert len(result.groups) == 0
    assert len(result.unique_transaction_ids) == 10000


def test_duplicate_detection_ordering_independent():
    base = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    a = _tx("a", timestamp=base, asset="USDT", quantity=Decimal("100"))
    b = _tx("b", timestamp=base, asset="USDT", quantity=Decimal("100"))

    result_ab = DuplicateDetector().detect([a, b])
    result_ba = DuplicateDetector().detect([b, a])

    assert len(result_ab.groups) == len(result_ba.groups)
    assert result_ab.groups[0].classification == result_ba.groups[0].classification


def test_oversized_strong_identifier_bucket_never_skips_exact_duplicates():
    base = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    transactions = [
        _tx(f"tx_{i}", source_transaction_id="TID-1", timestamp=base, asset="BTC", quantity=Decimal("1"))
        for i in range(600)
    ]
    result = DuplicateDetector(max_fingerprint_bucket_size=500).detect(transactions)
    assert len(result.groups) == 1
    assert result.groups[0].classification == DuplicateClassification.PROBABLE_DUPLICATE
    assert len(result.groups[0].transaction_ids) == 600


def test_oversized_fingerprint_bucket_preserves_duplicates_at_boundary():
    base = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    transactions = []
    for i in range(600):
        tx = _tx(
            f"tx_{i}",
            timestamp=base + timedelta(seconds=i * 2),
            asset="BTC",
            quantity=Decimal("0.01"),
        )
        transactions.append(tx)

    result = DuplicateDetector(timestamp_tolerance_seconds=1, max_fingerprint_bucket_size=500).detect(transactions)
    assert len(result.groups) == 0
    assert len(result.unique_transaction_ids) == 600


# --- M026 P2 Hardening: Cross-Exchange Duplicate Grouping ---


def test_same_source_same_transaction_id_is_duplicate():
    txs = [
        _tx("tx-a", source=Source.BINANCE),
        _tx("tx-a", source=Source.BINANCE),
    ]
    result = DuplicateDetector().detect(txs)
    assert len(result.groups) == 1
    assert result.groups[0].classification == DuplicateClassification.EXACT_DUPLICATE
    assert len(result.unique_transaction_ids) == 1


def test_cross_exchange_same_transaction_id_not_automatic_duplicate():
    txs = [
        _tx("tx-a", source=Source.BINANCE),
        _tx("tx-a", source=Source.COINBASE),
    ]
    result = DuplicateDetector().detect(txs)
    assert len(result.groups) == 0
    assert len(result.unique_transaction_ids) == 2


def test_cross_exchange_same_tx_hash_may_match_via_transfer():
    txs = [
        _tx("tx-1", source=Source.BINANCE, transaction_type=TransactionType.TRANSFER, tx_hash="abc123"),
        _tx("tx-2", source=Source.COINBASE, transaction_type=TransactionType.TRANSFER, tx_hash="abc123"),
    ]
    result = DuplicateDetector().detect(txs)
    assert len(result.groups) == 1
    assert result.groups[0].classification == DuplicateClassification.PROBABLE_DUPLICATE


def test_same_source_same_tx_hash_is_duplicate():
    txs = [
        _tx("tx-1", source=Source.BINANCE, tx_hash="abc123"),
        _tx("tx-2", source=Source.BINANCE, tx_hash="abc123"),
    ]
    result = DuplicateDetector().detect(txs)
    assert len(result.groups) == 1


def test_cross_exchange_different_values_not_duplicate():
    txs = [
        _tx("tx-1", source=Source.BINANCE, asset="BTC", quantity=Decimal("1")),
        _tx("tx-2", source=Source.COINBASE, asset="ETH", quantity=Decimal("2")),
    ]
    result = DuplicateDetector().detect(txs)
    assert len(result.groups) == 0
    assert len(result.unique_transaction_ids) == 2


def test_exact_duplicate_same_source_remains_duplicate():
    txs = [
        _tx("tx-a", source=Source.BINANCE, asset="BTC", quantity=Decimal("1"), value=Decimal("50000")),
        _tx("tx-a", source=Source.BINANCE, asset="BTC", quantity=Decimal("1"), value=Decimal("50000")),
    ]
    result = DuplicateDetector().detect(txs)
    assert len(result.groups) == 1
    assert result.groups[0].classification == DuplicateClassification.EXACT_DUPLICATE
