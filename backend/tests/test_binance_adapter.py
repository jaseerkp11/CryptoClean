import csv
from decimal import Decimal
import pytest

from backend.adapters.base import AdapterResult
from backend.adapters.binance.transaction_record import BinanceTransactionRecordAdapter
from backend.models.transaction import CanonicalTransaction, Source, TransactionType


def _load_sample_rows() -> list[dict]:
    rows = []
    with open(r"C:\Projects\CryptoClean\sample_data\binance_transaction_record_sample.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def test_real_binance_headers_recognized():
    adapter = BinanceTransactionRecordAdapter(timezone="UTC")
    rows = _load_sample_rows()
    result = adapter.adapt(rows)
    assert isinstance(result, AdapterResult)
    assert len(result.transactions) == len(rows)


def test_missing_required_column_rejected():
    adapter = BinanceTransactionRecordAdapter(timezone="UTC")
    rows = [
        {"Time": "2024-10-20 21:01:19", "Account": "Spot", "Operation": "Deposit", "Coin": "SOL", "Change": "+0.0215519", "Remark": ""}
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 0
    assert len(result.errors) > 0
    assert "Missing required columns" in result.errors[0]


def test_decimal_precision_preserved():
    adapter = BinanceTransactionRecordAdapter(timezone="UTC")
    rows = [
        {"User ID": "REDACTED", "Time": "2024-10-20 21:01:19", "Account": "Spot", "Operation": "Deposit", "Coin": "SOL", "Change": "0.0215519", "Remark": ""}
    ]
    result = adapter.adapt(rows)
    assert isinstance(result.transactions[0].quantity, Decimal)
    assert result.transactions[0].quantity == Decimal("0.0215519")


def test_deposit_mapping():
    adapter = BinanceTransactionRecordAdapter(timezone="UTC")
    rows = [
        {"User ID": "REDACTED", "Time": "2024-10-20 21:01:19", "Account": "Spot", "Operation": "Deposit", "Coin": "SOL", "Change": "+0.0215519", "Remark": ""}
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    tx = result.transactions[0]
    assert tx.transaction_type == TransactionType.DEPOSIT
    assert tx.asset == "SOL"
    assert tx.quantity == Decimal("0.0215519")
    assert tx.source == Source.BINANCE


def test_convert_mapping():
    adapter = BinanceTransactionRecordAdapter(timezone="UTC")
    rows = [
        {"User ID": "REDACTED", "Time": "2024-10-20 21:01:19", "Account": "Spot", "Operation": "Binance Convert", "Coin": "USDT", "Change": "+3.42578053", "Remark": ""},
        {"User ID": "REDACTED", "Time": "2024-10-20 21:01:19", "Account": "Spot", "Operation": "Binance Convert", "Coin": "SOL", "Change": "-0.0215519", "Remark": ""},
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 2
    for tx in result.transactions:
        assert tx.transaction_type == TransactionType.UNKNOWN
        assert "Binance Convert" in (tx.metadata or {}).get("source_operation", "")
    assert any("Binance Convert rows should be grouped later" in w for w in result.warnings)


def test_transfer_mapping():
    adapter = BinanceTransactionRecordAdapter(timezone="UTC")
    rows = [
        {"User ID": "REDACTED", "Time": "2024-10-20 21:02:00", "Account": "Spot", "Operation": "Transfer Between Spot and UM Futures", "Coin": "USDT", "Change": "-100.0", "Remark": ""},
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    tx = result.transactions[0]
    assert tx.transaction_type == TransactionType.TRANSFER
    assert tx.quantity == Decimal("100.0")


def test_fee_mapping():
    adapter = BinanceTransactionRecordAdapter(timezone="UTC")
    rows = [
        {"User ID": "REDACTED", "Time": "2024-10-20 21:04:00", "Account": "Spot", "Operation": "Fee", "Coin": "BNB", "Change": "-0.0001", "Remark": "TradeID - 14707925"}
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    tx = result.transactions[0]
    assert tx.transaction_type == TransactionType.FEE
    assert tx.quantity == Decimal("0.0001")
    assert tx.source_transaction_id == "14707925"


def test_funding_fee_mapping():
    adapter = BinanceTransactionRecordAdapter(timezone="UTC")
    rows = [
        {"User ID": "REDACTED", "Time": "2024-10-20 21:05:00", "Account": "Funding", "Operation": "Funding Fee", "Coin": "USDT", "Change": "-0.5", "Remark": ""}
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    tx = result.transactions[0]
    assert tx.transaction_type == TransactionType.FEE
    assert any("Funding Fee preserved in metadata" in w for w in result.warnings)


def test_realized_pnl_does_not_become_trade():
    adapter = BinanceTransactionRecordAdapter(timezone="UTC")
    rows = [
        {"User ID": "REDACTED", "Time": "2024-10-20 21:06:00", "Account": "Spot", "Operation": "Realized Profit and Loss", "Coin": "USDT", "Change": "+10.0", "Remark": "TradeID - 12345"}
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    tx = result.transactions[0]
    assert tx.transaction_type == TransactionType.UNKNOWN
    assert tx.source_transaction_id == "12345"


def test_p2p_does_not_become_trade():
    adapter = BinanceTransactionRecordAdapter(timezone="UTC")
    rows = [
        {"User ID": "REDACTED", "Time": "2024-10-20 21:07:00", "Account": "Spot", "Operation": "P2P Trading", "Coin": "USDT", "Change": "+100.0", "Remark": "P2P - 22775202417291345920"}
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    tx = result.transactions[0]
    assert tx.transaction_type == TransactionType.UNKNOWN
    assert tx.source_transaction_id == "22775202417291345920"
    assert any("P2P Trading requires a dedicated parser" in w for w in result.warnings)


def test_crypto_box_mapping():
    adapter = BinanceTransactionRecordAdapter(timezone="UTC")
    rows = [
        {"User ID": "REDACTED", "Time": "2024-10-20 21:08:00", "Account": "Spot", "Operation": "Crypto Box", "Coin": "BNB", "Change": "+0.01", "Remark": ""}
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    tx = result.transactions[0]
    assert tx.transaction_type == TransactionType.REWARD


def test_earn_subscription_does_not_become_trade():
    adapter = BinanceTransactionRecordAdapter(timezone="UTC")
    rows = [
        {"User ID": "REDACTED", "Time": "2024-10-20 21:10:00", "Account": "Spot", "Operation": "Simple Earn Flexible Subscription", "Coin": "USDT", "Change": "-100.0", "Remark": ""}
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    tx = result.transactions[0]
    assert tx.transaction_type == TransactionType.TRANSFER
    assert tx.quantity == Decimal("100.0")


def test_unknown_operation_becomes_unknown():
    adapter = BinanceTransactionRecordAdapter(timezone="UTC")
    rows = [
        {"User ID": "REDACTED", "Time": "2024-10-20 21:12:00", "Account": "Spot", "Operation": "Unknown Operation", "Coin": "XRP", "Change": "+10.0", "Remark": ""}
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    tx = result.transactions[0]
    assert tx.transaction_type == TransactionType.UNKNOWN
    assert any("Unrecognized Binance operation: Unknown Operation" in w for w in result.warnings)


def test_deterministic_transaction_id():
    adapter = BinanceTransactionRecordAdapter(timezone="UTC")
    rows = [
        {"User ID": "REDACTED", "Time": "2024-10-20 21:01:19", "Account": "Spot", "Operation": "Deposit", "Coin": "SOL", "Change": "+0.0215519", "Remark": ""}
    ]
    result1 = adapter.adapt(rows)
    result2 = adapter.adapt(rows)
    assert result1.transactions[0].transaction_id == result2.transactions[0].transaction_id


def test_same_row_produces_same_transaction_id():
    adapter = BinanceTransactionRecordAdapter(timezone="UTC")
    row = {"User ID": "REDACTED", "Time": "2024-10-20 21:01:19", "Account": "Spot", "Operation": "Deposit", "Coin": "SOL", "Change": "+0.0215519", "Remark": ""}
    result = adapter.adapt([row])
    first_id = result.transactions[0].transaction_id
    result2 = adapter.adapt([row])
    assert result2.transactions[0].transaction_id == first_id


def test_user_id_not_in_metadata():
    adapter = BinanceTransactionRecordAdapter(timezone="UTC")
    rows = [
        {"User ID": "REDACTED", "Time": "2024-10-20 21:01:19", "Account": "Spot", "Operation": "Deposit", "Coin": "SOL", "Change": "+0.0215519", "Remark": ""}
    ]
    result = adapter.adapt(rows)
    tx = result.transactions[0]
    metadata = tx.metadata or {}
    assert "User ID" not in metadata
    assert "REDACTED" not in str(metadata)


def test_trade_id_extraction():
    adapter = BinanceTransactionRecordAdapter(timezone="UTC")
    rows = [
        {"User ID": "REDACTED", "Time": "2024-10-20 21:04:00", "Account": "Spot", "Operation": "Fee", "Coin": "BNB", "Change": "-0.0001", "Remark": "TradeID - 14707925"}
    ]
    result = adapter.adapt(rows)
    assert result.transactions[0].source_transaction_id == "14707925"


def test_p2p_identifier_extraction():
    adapter = BinanceTransactionRecordAdapter(timezone="UTC")
    rows = [
        {"User ID": "REDACTED", "Time": "2024-10-20 21:07:00", "Account": "Spot", "Operation": "P2P Trading", "Coin": "USDT", "Change": "+100.0", "Remark": "P2P - 22775202417291345920"}
    ]
    result = adapter.adapt(rows)
    assert result.transactions[0].source_transaction_id == "22775202417291345920"


def test_timezone_must_be_explicit():
    with pytest.raises(ValueError, match="Timezone must be explicitly provided"):
        BinanceTransactionRecordAdapter(None)


def test_invalid_timezone_rejected():
    with pytest.raises(ValueError, match="Invalid timezone"):
        BinanceTransactionRecordAdapter(timezone="Not/A_Timezone")


def test_no_float_conversion():
    adapter = BinanceTransactionRecordAdapter(timezone="UTC")
    rows = [
        {"User ID": "REDACTED", "Time": "2024-10-20 21:01:19", "Account": "Spot", "Operation": "Deposit", "Coin": "SOL", "Change": "0.0215519", "Remark": ""}
    ]
    result = adapter.adapt(rows)
    assert isinstance(result.transactions[0].quantity, Decimal)


def test_signed_change_preserved_in_metadata():
    adapter = BinanceTransactionRecordAdapter(timezone="UTC")
    rows = [
        {"User ID": "REDACTED", "Time": "2024-10-20 21:01:19", "Account": "Spot", "Operation": "Fee", "Coin": "BNB", "Change": "-0.0001", "Remark": ""}
    ]
    result = adapter.adapt(rows)
    tx = result.transactions[0]
    assert (tx.metadata or {}).get("source_change_signed") == "-0.0001"
    assert tx.quantity == Decimal("0.0001")


def test_empty_rows():
    adapter = BinanceTransactionRecordAdapter(timezone="UTC")
    result = adapter.adapt([])
    assert len(result.transactions) == 0
    assert len(result.errors) == 1
    assert "No rows provided" in result.errors[0]
