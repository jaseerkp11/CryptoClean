import pytest
from decimal import Decimal

from backend.adapters.base import AdapterResult
from backend.adapters.coinbase.transaction_record import CoinbaseTransactionRecordAdapter
from backend.models.transaction import CanonicalTransaction, Source, Side, TransactionType


def _adapter():
    return CoinbaseTransactionRecordAdapter(timezone="UTC")


def test_valid_coinbase_buy_maps_to_trade_buy():
    adapter = _adapter()
    rows = [
        {
            "Timestamp": "2024-01-01 00:00:00 UTC",
            "Transaction Type": "Buy",
            "Asset": "BTC",
            "Quantity Transacted": "0.01",
            "Spot Price Currency": "USD",
            "Spot Price at Transaction": "30000",
            "Subtotal": "300",
            "Total (inclusive of fees)": "300.5",
            "Fees": "0.5",
            "Notes": "coinbase purchase",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    tx = result.transactions[0]
    assert tx.source == Source.COINBASE
    assert tx.transaction_type == TransactionType.TRADE
    assert tx.side == Side.BUY
    assert tx.asset == "BTC"
    assert tx.quantity == pytest.approx(Decimal("0.01"))
    assert tx.quote_asset == "USD"
    assert tx.price == Decimal("30000")
    assert tx.value == Decimal("300.5")
    assert tx.fee == Decimal("0.5")
    assert tx.metadata["source_remark"] == "coinbase purchase"


def test_valid_coinbase_sell_maps_to_trade_sell():
    adapter = _adapter()
    rows = [
        {
            "Timestamp": "2024-01-01 00:00:00 UTC",
            "Transaction Type": "Sell",
            "Asset": "BTC",
            "Quantity Transacted": "0.01",
            "Spot Price Currency": "USD",
            "Spot Price at Transaction": "31000",
            "Subtotal": "310",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    tx = result.transactions[0]
    assert tx.transaction_type == TransactionType.TRADE
    assert tx.side == Side.SELL


def test_coinbase_send_maps_to_withdrawal():
    adapter = _adapter()
    rows = [
        {
            "Timestamp": "2024-01-01 00:00:00 UTC",
            "Transaction Type": "Send",
            "Asset": "BTC",
            "Quantity Transacted": "0.01",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    assert result.transactions[0].transaction_type == TransactionType.WITHDRAWAL
    assert result.transactions[0].side is None


def test_coinbase_receive_maps_to_deposit():
    adapter = _adapter()
    rows = [
        {
            "Timestamp": "2024-01-01 00:00:00 UTC",
            "Transaction Type": "Receive",
            "Asset": "BTC",
            "Quantity Transacted": "0.01",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    assert result.transactions[0].transaction_type == TransactionType.DEPOSIT
    assert result.transactions[0].side is None


def test_coinbase_convert_maps_to_swap():
    adapter = _adapter()
    rows = [
        {
            "Timestamp": "2024-01-01 00:00:00 UTC",
            "Transaction Type": "Convert",
            "Asset": "BTC",
            "Quantity Transacted": "0.01",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    assert result.transactions[0].transaction_type == TransactionType.SWAP
    assert result.transactions[0].side is None


def test_unknown_transaction_type_maps_to_unknown():
    adapter = _adapter()
    rows = [
        {
            "Timestamp": "2024-01-01 00:00:00 UTC",
            "Transaction Type": "Something Else",
            "Asset": "BTC",
            "Quantity Transacted": "0.01",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    assert result.transactions[0].transaction_type == TransactionType.UNKNOWN
    assert result.transactions[0].side is None


def test_missing_required_column_rejected():
    adapter = _adapter()
    rows = [
        {
            "Timestamp": "2024-01-01 00:00:00 UTC",
            "Transaction Type": "Buy",
            "Asset": "BTC",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 0
    assert len(result.errors) > 0
    assert "Missing required columns" in result.errors[0]


def test_invalid_timestamp_rejected():
    adapter = _adapter()
    rows = [
        {
            "Timestamp": "not-a-date",
            "Transaction Type": "Buy",
            "Asset": "BTC",
            "Quantity Transacted": "0.01",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 0
    assert len(result.errors) > 0


def test_invalid_decimal_rejected():
    adapter = _adapter()
    rows = [
        {
            "Timestamp": "2024-01-01 00:00:00 UTC",
            "Transaction Type": "Buy",
            "Asset": "BTC",
            "Quantity Transacted": "not-a-number",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 0
    assert len(result.errors) > 0


def test_nan_decimal_rejected():
    adapter = _adapter()
    rows = [
        {
            "Timestamp": "2024-01-01 00:00:00 UTC",
            "Transaction Type": "Buy",
            "Asset": "BTC",
            "Quantity Transacted": "NaN",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 0
    assert len(result.errors) > 0


def test_infinity_decimal_rejected():
    adapter = _adapter()
    rows = [
        {
            "Timestamp": "2024-01-01 00:00:00 UTC",
            "Transaction Type": "Buy",
            "Asset": "BTC",
            "Quantity Transacted": "Infinity",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 0
    assert len(result.errors) > 0


def test_non_positive_quantity_rejected():
    adapter = _adapter()
    rows = [
        {
            "Timestamp": "2024-01-01 00:00:00 UTC",
            "Transaction Type": "Buy",
            "Asset": "BTC",
            "Quantity Transacted": "0",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 0
    assert len(result.errors) > 0


def test_deterministic_transaction_id():
    adapter = _adapter()
    rows = [
        {
            "Timestamp": "2024-01-01 00:00:00 UTC",
            "Transaction Type": "Buy",
            "Asset": "BTC",
            "Quantity Transacted": "0.01",
            "Subtotal": "300",
        }
    ]
    r1 = adapter.adapt(rows)
    r2 = adapter.adapt(rows)
    assert r1.transactions[0].transaction_id == r2.transactions[0].transaction_id


def test_malformed_row_rejected_without_partial_transaction():
    adapter = _adapter()
    rows = [
        {
            "Timestamp": "2024-01-01 00:00:00 UTC",
            "Transaction Type": "Buy",
            "Asset": "BTC",
            "Quantity Transacted": "0.01",
        },
        {
            "Timestamp": "not-a-date",
            "Transaction Type": "Buy",
            "Asset": "ETH",
            "Quantity Transacted": "1.0",
        },
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    assert len(result.errors) == 1


def test_optional_columns_absent_still_adapts():
    adapter = _adapter()
    rows = [
        {
            "Timestamp": "2024-01-01 00:00:00 UTC",
            "Transaction Type": "Buy",
            "Asset": "BTC",
            "Quantity Transacted": "0.01",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    tx = result.transactions[0]
    assert tx.quote_asset is None
    assert tx.price is None
    assert tx.value is None
    assert tx.fee is None
    assert tx.metadata.get("source_remark") is None


def test_fee_asset_preserved():
    adapter = _adapter()
    rows = [
        {
            "Timestamp": "2024-01-01 00:00:00 UTC",
            "Transaction Type": "Buy",
            "Asset": "BTC",
            "Quantity Transacted": "0.01",
            "Fees": "0.5",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    assert result.transactions[0].fee == Decimal("0.5")


def test_value_computed_from_price_when_subtotal_absent():
    adapter = _adapter()
    rows = [
        {
            "Timestamp": "2024-01-01 00:00:00 UTC",
            "Transaction Type": "Buy",
            "Asset": "BTC",
            "Quantity Transacted": "0.01",
            "Spot Price Currency": "USD",
            "Spot Price at Transaction": "30000",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    assert result.transactions[0].value == Decimal("300")


def test_total_preferred_over_subtotal_for_value():
    adapter = _adapter()
    rows = [
        {
            "Timestamp": "2024-01-01 00:00:00 UTC",
            "Transaction Type": "Buy",
            "Asset": "BTC",
            "Quantity Transacted": "0.01",
            "Subtotal": "300",
            "Total (inclusive of fees)": "300.5",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    assert result.transactions[0].value == Decimal("300.5")
