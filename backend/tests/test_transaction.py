from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import pytest
from pydantic import ValidationError

from backend.models.transaction import (
    CanonicalTransaction,
    Side,
    Source,
    TransactionType,
)


def _make_timestamp() -> datetime:
    return datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_valid_buy():
    tx = CanonicalTransaction(
        transaction_id="tx_1",
        source=Source.BINANCE,
        timestamp=_make_timestamp(),
        transaction_type=TransactionType.TRADE,
        side=Side.BUY,
        asset="BTC",
        quantity=Decimal("0.01"),
        quote_asset="USDT",
        price=Decimal("30000.00"),
        value=Decimal("300.00"),
        fee=Decimal("0.1"),
        fee_asset="BNB",
        fee_value=Decimal("0.1"),
        wallet="wallet_1",
        counterparty="binance",
        tx_hash="0xabc",
        confidence=0.99,
        notes="test buy",
        metadata={"raw": "data"},
    )
    assert tx.transaction_id == "tx_1"
    assert tx.side == Side.BUY
    assert tx.quantity == Decimal("0.01")


def test_valid_sell():
    tx = CanonicalTransaction(
        transaction_id="tx_2",
        source=Source.COINBASE,
        timestamp=_make_timestamp(),
        transaction_type=TransactionType.TRADE,
        side=Side.SELL,
        asset="BTC",
        quantity=Decimal("0.01"),
        quote_asset="USD",
        price=Decimal("31000.00"),
        value=Decimal("310.00"),
        fee=Decimal("0.5"),
        fee_asset="USD",
        fee_value=Decimal("0.5"),
        confidence=0.99,
    )
    assert tx.side == Side.SELL
    assert tx.transaction_type == TransactionType.TRADE


def test_zero_quantity_rejected():
    with pytest.raises(ValidationError):
        CanonicalTransaction(
            transaction_id="tx_zero",
            source=Source.BINANCE,
            timestamp=_make_timestamp(),
            transaction_type=TransactionType.TRADE,
            side=Side.BUY,
            asset="BTC",
            quantity=Decimal("0"),
            quote_asset="USDT",
            price=Decimal("30000.00"),
            confidence=1.0,
        )


def test_negative_quantity_rejected():
    with pytest.raises(ValidationError):
        CanonicalTransaction(
            transaction_id="tx_neg",
            source=Source.BINANCE,
            timestamp=_make_timestamp(),
            transaction_type=TransactionType.TRADE,
            side=Side.BUY,
            asset="BTC",
            quantity=Decimal("-1"),
            quote_asset="USDT",
            price=Decimal("30000.00"),
            confidence=1.0,
        )


def test_negative_fee_rejected():
    with pytest.raises(ValidationError):
        CanonicalTransaction(
            transaction_id="tx_fee",
            source=Source.BINANCE,
            timestamp=_make_timestamp(),
            transaction_type=TransactionType.TRADE,
            side=Side.BUY,
            asset="BTC",
            quantity=Decimal("0.01"),
            quote_asset="USDT",
            price=Decimal("30000.00"),
            fee=Decimal("-0.5"),
            confidence=1.0,
        )


def test_negative_fee_value_rejected():
    with pytest.raises(ValidationError):
        CanonicalTransaction(
            transaction_id="tx_fee_val",
            source=Source.BINANCE,
            timestamp=_make_timestamp(),
            transaction_type=TransactionType.TRADE,
            side=Side.BUY,
            asset="BTC",
            quantity=Decimal("0.01"),
            quote_asset="USDT",
            price=Decimal("30000.00"),
            fee=Decimal("0.5"),
            fee_value=Decimal("-0.5"),
            confidence=1.0,
        )


def test_valid_swap():
    tx = CanonicalTransaction(
        transaction_id="tx_3",
        source=Source.UNKNOWN,
        timestamp=_make_timestamp(),
        transaction_type=TransactionType.SWAP,
        asset="BTC",
        quantity=Decimal("0.01"),
        quote_asset="ETH",
        price=Decimal("15.0"),
        value=Decimal("15.0"),
        confidence=0.8,
    )
    assert tx.transaction_type == TransactionType.SWAP
    assert tx.side is None


def test_valid_deposit():
    tx = CanonicalTransaction(
        transaction_id="tx_4",
        source=Source.ETHEREUM,
        timestamp=_make_timestamp(),
        transaction_type=TransactionType.DEPOSIT,
        asset="ETH",
        quantity=Decimal("1.5"),
        wallet="0x123",
        tx_hash="0xdeposit",
        confidence=0.95,
    )
    assert tx.transaction_type == TransactionType.DEPOSIT
    assert tx.price is None


def test_valid_withdrawal():
    tx = CanonicalTransaction(
        transaction_id="tx_5",
        source=Source.SOLANA,
        timestamp=_make_timestamp(),
        transaction_type=TransactionType.WITHDRAWAL,
        asset="SOL",
        quantity=Decimal("10"),
        wallet="wallet_sol",
        tx_hash="0xwithdraw",
        confidence=0.95,
    )
    assert tx.transaction_type == TransactionType.WITHDRAWAL


def test_valid_transfer():
    tx = CanonicalTransaction(
        transaction_id="tx_6",
        source=Source.MANUAL,
        timestamp=_make_timestamp(),
        transaction_type=TransactionType.TRANSFER,
        asset="USDC",
        quantity=Decimal("100"),
        wallet="wallet_a",
        counterparty="wallet_b",
        confidence=0.9,
    )
    assert tx.transaction_type == TransactionType.TRANSFER


def test_valid_fee():
    tx = CanonicalTransaction(
        transaction_id="tx_7",
        source=Source.BINANCE,
        timestamp=_make_timestamp(),
        transaction_type=TransactionType.FEE,
        asset="BNB",
        quantity=Decimal("0.01"),
        fee=Decimal("0.01"),
        fee_asset="BNB",
        fee_value=Decimal("0.01"),
        confidence=1.0,
    )
    assert tx.transaction_type == TransactionType.FEE


def test_valid_reward():
    tx = CanonicalTransaction(
        transaction_id="tx_8",
        source=Source.UNKNOWN,
        timestamp=_make_timestamp(),
        transaction_type=TransactionType.REWARD,
        asset="BTC",
        quantity=Decimal("0.001"),
        confidence=0.7,
    )
    assert tx.transaction_type == TransactionType.REWARD


def test_valid_staking():
    tx = CanonicalTransaction(
        transaction_id="tx_9",
        source=Source.MANUAL,
        timestamp=_make_timestamp(),
        transaction_type=TransactionType.STAKING,
        asset="ETH",
        quantity=Decimal("1"),
        confidence=0.85,
    )
    assert tx.transaction_type == TransactionType.STAKING


def test_valid_airdrop():
    tx = CanonicalTransaction(
        transaction_id="tx_10",
        source=Source.UNKNOWN,
        timestamp=_make_timestamp(),
        transaction_type=TransactionType.AIRDROP,
        asset="TOKEN",
        quantity=Decimal("1000"),
        confidence=0.6,
    )
    assert tx.transaction_type == TransactionType.AIRDROP


def test_unknown_transaction():
    tx = CanonicalTransaction(
        transaction_id="tx_11",
        source=Source.UNKNOWN,
        timestamp=_make_timestamp(),
        transaction_type=TransactionType.UNKNOWN,
        asset="UNK",
        quantity=Decimal("1"),
        confidence=0.0,
    )
    assert tx.transaction_type == TransactionType.UNKNOWN


def test_decimal_precision_preservation():
    precise = Decimal("123456789.123456789123456789")
    tx = CanonicalTransaction(
        transaction_id="tx_12",
        source=Source.BINANCE,
        timestamp=_make_timestamp(),
        transaction_type=TransactionType.TRADE,
        side=Side.BUY,
        asset="BTC",
        quantity=precise,
        quote_asset="USDT",
        price=precise,
        value=precise,
        confidence=0.9,
    )
    assert isinstance(tx.quantity, Decimal)
    assert tx.quantity == precise
    assert isinstance(tx.price, Decimal)
    assert tx.price == precise
    assert isinstance(tx.value, Decimal)
    assert tx.value == precise


def test_invalid_confidence_too_high():
    with pytest.raises(ValidationError):
        CanonicalTransaction(
            transaction_id="tx_13",
            source=Source.BINANCE,
            timestamp=_make_timestamp(),
            transaction_type=TransactionType.TRADE,
            side=Side.BUY,
            asset="BTC",
            quantity=Decimal("0.01"),
            confidence=1.5,
        )


def test_invalid_confidence_too_low():
    with pytest.raises(ValidationError):
        CanonicalTransaction(
            transaction_id="tx_14",
            source=Source.BINANCE,
            timestamp=_make_timestamp(),
            transaction_type=TransactionType.TRADE,
            side=Side.BUY,
            asset="BTC",
            quantity=Decimal("0.01"),
            confidence=-0.1,
        )


def test_naive_timestamp_rejection():
    with pytest.raises(ValidationError):
        CanonicalTransaction(
            transaction_id="tx_15",
            source=Source.BINANCE,
            timestamp=datetime(2024, 1, 1, 0, 0, 0),
            transaction_type=TransactionType.TRADE,
            side=Side.BUY,
            asset="BTC",
            quantity=Decimal("0.01"),
            confidence=0.9,
        )


def test_missing_optional_fields():
    tx = CanonicalTransaction(
        transaction_id="tx_16",
        source=Source.UNKNOWN,
        timestamp=_make_timestamp(),
        transaction_type=TransactionType.UNKNOWN,
        asset="X",
        quantity=Decimal("1"),
        confidence=0.0,
    )
    assert tx.quote_asset is None
    assert tx.price is None
    assert tx.value is None
    assert tx.fee is None
    assert tx.fee_asset is None
    assert tx.fee_value is None
    assert tx.wallet is None
    assert tx.counterparty is None
    assert tx.tx_hash is None
    assert tx.notes is None
    assert tx.metadata is None


def test_blank_transaction_id_rejection():
    with pytest.raises(ValidationError):
        CanonicalTransaction(
            transaction_id="",
            source=Source.BINANCE,
            timestamp=_make_timestamp(),
            transaction_type=TransactionType.TRADE,
            side=Side.BUY,
            asset="BTC",
            quantity=Decimal("0.01"),
            confidence=0.9,
        )

    with pytest.raises(ValidationError):
        CanonicalTransaction(
            transaction_id="   ",
            source=Source.BINANCE,
            timestamp=_make_timestamp(),
            transaction_type=TransactionType.TRADE,
            side=Side.BUY,
            asset="BTC",
            quantity=Decimal("0.01"),
            confidence=0.9,
        )


def test_invalid_decimal_values():
    with pytest.raises(ValidationError):
        CanonicalTransaction(
            transaction_id="tx_17",
            source=Source.BINANCE,
            timestamp=_make_timestamp(),
            transaction_type=TransactionType.TRADE,
            side=Side.BUY,
            asset="BTC",
            quantity=Decimal("NaN"),
            confidence=0.9,
        )

    with pytest.raises(ValidationError):
        CanonicalTransaction(
            transaction_id="tx_18",
            source=Source.BINANCE,
            timestamp=_make_timestamp(),
            transaction_type=TransactionType.TRADE,
            side=Side.BUY,
            asset="BTC",
            quantity=Decimal("Infinity"),
            confidence=0.9,
        )

    with pytest.raises(ValidationError):
        CanonicalTransaction(
            transaction_id="tx_19",
            source=Source.BINANCE,
            timestamp=_make_timestamp(),
            transaction_type=TransactionType.TRADE,
            side=Side.BUY,
            asset="BTC",
            quantity=Decimal("-Infinity"),
            confidence=0.9,
        )


def test_json_serialization_preserves_decimals():
    tx = CanonicalTransaction(
        transaction_id="tx_20",
        source=Source.BINANCE,
        timestamp=_make_timestamp(),
        transaction_type=TransactionType.TRADE,
        side=Side.BUY,
        asset="BTC",
        quantity=Decimal("0.01000000"),
        quote_asset="USDT",
        price=Decimal("30000.123456789"),
        value=Decimal("300.00123456789"),
        fee=Decimal("0.1"),
        fee_asset="BNB",
        fee_value=Decimal("0.1"),
        confidence=0.99,
    )
    json_str = tx.model_dump_json()
    data = json.loads(json_str)
    assert data["quantity"] == "0.01000000"
    assert data["price"] == "30000.123456789"
    assert data["value"] == "300.00123456789"
    assert data["fee"] == "0.1"
    assert data["fee_value"] == "0.1"
    assert isinstance(data["quantity"], str)
    assert isinstance(data["price"], str)


def test_extremely_precise_quantity_not_converted_to_float():
    precise = Decimal("123456789.123456789123456789")
    tx = CanonicalTransaction(
        transaction_id="tx_21",
        source=Source.BINANCE,
        timestamp=_make_timestamp(),
        transaction_type=TransactionType.TRADE,
        side=Side.BUY,
        asset="BTC",
        quantity=precise,
        confidence=0.9,
    )
    assert isinstance(tx.quantity, Decimal)
    assert tx.quantity == precise
    dumped = tx.model_dump(mode="json")
    assert isinstance(dumped["quantity"], str)


def test_side_required_for_trade():
    with pytest.raises(ValidationError):
        CanonicalTransaction(
            transaction_id="tx_22",
            source=Source.BINANCE,
            timestamp=_make_timestamp(),
            transaction_type=TransactionType.TRADE,
            asset="BTC",
            quantity=Decimal("0.01"),
            confidence=0.9,
        )


def test_side_not_allowed_for_non_trade():
    with pytest.raises(ValidationError):
        CanonicalTransaction(
            transaction_id="tx_23",
            source=Source.BINANCE,
            timestamp=_make_timestamp(),
            transaction_type=TransactionType.DEPOSIT,
            side=Side.BUY,
            asset="BTC",
            quantity=Decimal("0.01"),
            confidence=0.9,
        )


def test_metadata_rejects_sensitive_keys():
    with pytest.raises(ValidationError):
        CanonicalTransaction(
            transaction_id="tx_24",
            source=Source.BINANCE,
            timestamp=_make_timestamp(),
            transaction_type=TransactionType.TRADE,
            side=Side.BUY,
            asset="BTC",
            quantity=Decimal("0.01"),
            confidence=0.9,
            metadata={"api_key": "secret123"},
        )

    with pytest.raises(ValidationError):
        CanonicalTransaction(
            transaction_id="tx_25",
            source=Source.BINANCE,
            timestamp=_make_timestamp(),
            transaction_type=TransactionType.TRADE,
            side=Side.BUY,
            asset="BTC",
            quantity=Decimal("0.01"),
            confidence=0.9,
            metadata={"password": "hunter2"},
        )


def test_model_is_frozen():
    tx = CanonicalTransaction(
        transaction_id="tx_26",
        source=Source.BINANCE,
        timestamp=_make_timestamp(),
        transaction_type=TransactionType.TRADE,
        side=Side.BUY,
        asset="BTC",
        quantity=Decimal("0.01"),
        confidence=0.9,
    )
    with pytest.raises(ValueError):
        tx.confidence = 0.5
