import io
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.adapters.binance.spot_trade_history import BinanceSpotTradeHistoryAdapter
from backend.models.transaction import CanonicalTransaction, Source, Side, TransactionType
from backend.processing.pipeline import ProcessingPipeline
from backend.main import app

VALID_CSV = """Date(UTC),Pair,Type,Order Price,Amount,Average Price,Filled,Total,Fee,Fee Coin
2024-01-01 12:00:00,BTC/USDT,Buy,30000,0.01,30000,0.01,300,0.1,BNB
2024-01-02 12:00:00,BTC/USDT,Sell,31000,0.01,31000,0.01,310,0.1,BNB
2024-01-03 12:00:00,ETH/USDT,Buy,2000,0.5,2000,0.5,1000,0.2,BNB
2024-01-04 12:00:00,ETH/USDT,Sell,2100,0.5,2100,0.5,1050,0.2,USDT
2024-01-05 12:00:00,BNB/USDT,Buy,300,1.0,300,1.0,300,0.01,BNB
2024-01-06 12:00:00,BNB/USDT,Sell,290,1.0,290,1.0,290,0.01,USDT
2024-01-07 12:00:00,BTC/USDT,Buy,30000.123456789,0.123456789012345,30000.123456789,0.123456789012345,3700.123456789,0.000000000123456,BNB
2024-01-08 12:00:00,BTC/USDT,Buy,30000,0.01,30000,0.01,300,0.1,BNB
2024-01-08 12:00:00,BTC/USDT,Buy,30000,0.01,30000,0.01,300,0.1,BNB
2024-01-09 12:00:00,BTC/USDT,Sell,31000,0.01,31000,0.01,310,0.1,BNB
"""

TRADE_ID_CSV = """Date(UTC),Pair,Type,Order Price,Amount,Total,Fee,Fee Coin,Trade ID,Order ID
2024-01-01 12:00:00,BTC/USDT,Buy,30000,0.01,300,0.1,BNB,trade-123,order-456
"""

ALTERNATIVE_COLUMNS_CSV = """Date(UTC),Symbol,Side,Price,Executed,Amount,Fee,Fee Coin
2024-01-01 12:00:00,ETH/USDT,Buy,2000,0.5,1000,0.2,BNB
"""

NO_SLASH_PAIR_CSV = """Date(UTC),Pair,Type,Order Price,Amount,Total,Fee,Fee Coin
2024-01-01 12:00:00,ETHUSDT,Buy,2000,0.5,1000,0.2,BNB
"""

UNKNOWN_SYMBOL_CSV = """Date(UTC),Pair,Type,Order Price,Amount,Total,Fee,Fee Coin
2024-01-01 12:00:00,XYZABC,Buy,100,1,100,0.1,BNB
"""

INVALID_SIDE_CSV = """Date(UTC),Pair,Type,Order Price,Amount,Total,Fee,Fee Coin
2024-01-01 12:00:00,BTC/USDT,Hold,30000,0.01,300,0.1,BNB
"""

INVALID_TIMESTAMP_CSV = """Date(UTC),Pair,Type,Order Price,Amount,Total,Fee,Fee Coin
not-a-date,BTC/USDT,Buy,30000,0.01,300,0.1,BNB
"""

MALFORMED_NUMERIC_CSV = """Date(UTC),Pair,Type,Order Price,Amount,Total,Fee,Fee Coin
2024-01-01 12:00:00,BTC/USDT,Buy,abc,0.01,300,0.1,BNB
"""

MISSING_COLUMNS_CSV = """Date(UTC),Pair,Type,Order Price
2024-01-01 12:00:00,BTC/USDT,Buy,30000
"""

NAN_INF_CSV = """Date(UTC),Pair,Type,Order Price,Amount,Total,Fee,Fee Coin
2024-01-01 12:00:00,BTC/USDT,Buy,30000,NaN,300,0.1,BNB
2024-01-02 12:00:00,BTC/USDT,Sell,31000,Infinity,310,0.1,BNB
"""

USER_ID_CSV = """Date(UTC),Pair,Type,Order Price,Amount,Total,Fee,Fee Coin,User ID
2024-01-01 12:00:00,BTC/USDT,Buy,30000,0.01,300,0.1,BNB,some-user-id
"""


def _adapter():
    return BinanceSpotTradeHistoryAdapter(timezone="UTC")


def _pipeline():
    return ProcessingPipeline()


# 1. successful BUY
def test_successful_buy():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
            "Fee": "0.1",
            "Fee Coin": "BNB",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    tx = result.transactions[0]
    assert tx.transaction_type == TransactionType.TRADE
    assert tx.side == Side.BUY
    assert tx.asset == "BTC"
    assert tx.quantity == Decimal("0.01")
    assert tx.price == Decimal("30000")
    assert tx.value == Decimal("300")
    assert tx.fee == Decimal("0.1")
    assert tx.fee_asset == "BNB"
    assert tx.quote_asset == "USDT"


# 2. successful SELL
def test_successful_sell():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Sell",
            "Order Price": "31000",
            "Amount": "0.01",
            "Total": "310",
            "Fee": "0.1",
            "Fee Coin": "BNB",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    tx = result.transactions[0]
    assert tx.side == Side.SELL
    assert tx.asset == "BTC"
    assert tx.quantity == Decimal("0.01")
    assert tx.value == Decimal("310")


# 3. canonical TRADE type
def test_canonical_trade_type():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
        }
    ]
    result = adapter.adapt(rows)
    assert result.transactions[0].transaction_type == TransactionType.TRADE


# 4. BUY side
def test_buy_side():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
        }
    ]
    result = adapter.adapt(rows)
    assert result.transactions[0].side == Side.BUY


# 5. SELL side
def test_sell_side():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Sell",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
        }
    ]
    result = adapter.adapt(rows)
    assert result.transactions[0].side == Side.SELL


# 6. quantity Decimal
def test_quantity_decimal():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.123456789012345",
            "Total": "3700.123456789",
        }
    ]
    result = adapter.adapt(rows)
    assert isinstance(result.transactions[0].quantity, Decimal)
    assert result.transactions[0].quantity == Decimal("0.123456789012345")


# 7. price Decimal
def test_price_decimal():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000.123456789",
            "Amount": "0.01",
            "Total": "300.00123456789",
        }
    ]
    result = adapter.adapt(rows)
    assert isinstance(result.transactions[0].price, Decimal)
    assert result.transactions[0].price == Decimal("30000.123456789")


# 8. value Decimal
def test_value_decimal():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300.123456789",
        }
    ]
    result = adapter.adapt(rows)
    assert isinstance(result.transactions[0].value, Decimal)
    assert result.transactions[0].value == Decimal("300.123456789")


# 9. fee Decimal
def test_fee_decimal():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
            "Fee": "0.000000000123456",
            "Fee Coin": "BNB",
        }
    ]
    result = adapter.adapt(rows)
    assert isinstance(result.transactions[0].fee, Decimal)
    assert result.transactions[0].fee == Decimal("0.000000000123456")


# 10. fee asset
def test_fee_asset():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
            "Fee": "0.1",
            "Fee Coin": "BNB",
        }
    ]
    result = adapter.adapt(rows)
    assert result.transactions[0].fee_asset == "BNB"


# 11. trade ID preserved as source_transaction_id
def test_trade_id_preserved():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
            "Trade ID": "trade-789",
        }
    ]
    result = adapter.adapt(rows)
    assert result.transactions[0].source_transaction_id == "trade-789"


# 12. order ID preserved in metadata
def test_order_id_preserved():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
            "Order ID": "order-456",
        }
    ]
    result = adapter.adapt(rows)
    assert result.transactions[0].metadata.get("source_order_id") == "order-456"


# 13. deterministic transaction ID
def test_deterministic_transaction_id():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
        }
    ]
    r1 = adapter.adapt(rows)
    r2 = adapter.adapt(rows)
    assert r1.transactions[0].transaction_id == r2.transactions[0].transaction_id


# 14. duplicate import stability
def test_duplicate_import_stability():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
            "Trade ID": "dup-1",
        },
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
            "Trade ID": "dup-1",
        },
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 2
    assert result.transactions[0].transaction_id == result.transactions[1].transaction_id


# 15. naive timestamps default to UTC when timezone omitted
def test_naive_timestamps_default_to_utc():
    adapter = BinanceSpotTradeHistoryAdapter(timezone=None)
    rows = [
        {"Date(UTC)": "2024-01-01 12:00:00", "Pair": "BTC/USDT", "Type": "Buy", "Order Price": "30000", "Amount": "0.01"}
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    assert result.transactions[0].timestamp.tzinfo is not None


# 16. explicit timezone accepted
def test_explicit_timezone_accepted():
    adapter = BinanceSpotTradeHistoryAdapter(timezone="UTC")
    assert adapter.timezone is not None


# 16. explicit timezone accepted
def test_explicit_timezone_accepted():
    adapter = BinanceSpotTradeHistoryAdapter(timezone="UTC")
    assert adapter.timezone is not None


# 17. invalid timezone rejected
def test_invalid_timezone_rejected():
    with pytest.raises(ValueError, match="Invalid timezone"):
        BinanceSpotTradeHistoryAdapter(timezone="Not/A_Timezone")


# 18. invalid Decimal handled
def test_invalid_decimal_handled():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "not_a_number",
            "Amount": "0.01",
            "Total": "300",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 0
    assert len(result.errors) == 1


# 19. NaN rejected
def test_nan_rejected():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "NaN",
            "Total": "300",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 0
    assert len(result.errors) == 1


# 20. Infinity rejected
def test_infinity_rejected():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "Infinity",
            "Total": "300",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 0
    assert len(result.errors) == 1


# 21. missing required columns
def test_missing_required_columns():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 0
    assert len(result.errors) == 1
    assert "Missing required column" in result.errors[0]


# 22. invalid side
def test_invalid_side():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Hold",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 0
    assert len(result.errors) == 1
    assert "Invalid Side" in result.errors[0]


# 23. unknown symbol preserved
def test_unknown_symbol_preserved():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "XYZABC",
            "Type": "Buy",
            "Order Price": "100",
            "Amount": "1",
            "Total": "100",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    assert result.transactions[0].asset == "XYZABC"
    assert result.transactions[0].quote_asset is None
    assert any("Unable to resolve Pair" in w for w in result.warnings)


# 24. quote-asset resolution with slash
def test_quote_asset_resolution_with_slash():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "ETH/USDT",
            "Type": "Buy",
            "Order Price": "2000",
            "Amount": "0.5",
            "Total": "1000",
        }
    ]
    result = adapter.adapt(rows)
    assert result.transactions[0].asset == "ETH"
    assert result.transactions[0].quote_asset == "USDT"


# 25. quote-asset resolution without slash
def test_quote_asset_resolution_no_slash():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "ETHUSDT",
            "Type": "Buy",
            "Order Price": "2000",
            "Amount": "0.5",
            "Total": "1000",
        }
    ]
    result = adapter.adapt(rows)
    assert result.transactions[0].asset == "ETH"
    assert result.transactions[0].quote_asset == "USDT"


# 26. BNB fee
def test_bnb_fee():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
            "Fee": "0.1",
            "Fee Coin": "BNB",
        }
    ]
    result = adapter.adapt(rows)
    assert result.transactions[0].fee == Decimal("0.1")
    assert result.transactions[0].fee_asset == "BNB"


# 27. quote-currency fee
def test_quote_currency_fee():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "ETH/USDT",
            "Type": "Sell",
            "Price": "2000",
            "Quantity": "0.5",
            "Amount": "1000",
            "Fee": "0.2",
            "Fee Coin": "USDT",
        }
    ]
    result = adapter.adapt(rows)
    assert result.transactions[0].fee == Decimal("0.2")
    assert result.transactions[0].fee_asset == "USDT"


# 28. User ID privacy
def test_user_id_not_in_output():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
            "User ID": "secret-user",
        }
    ]
    result = adapter.adapt(rows)
    output = str(result.model_dump())
    assert "secret-user" not in output
    assert "User ID" not in output
    for tx in result.transactions:
        assert "User ID" not in (tx.metadata or {})


# 29. metadata no secrets
def test_metadata_no_secrets():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
            "User ID": "secret-user",
            "API Key": "abc123",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    tx = result.transactions[0]
    assert "User ID" not in (tx.metadata or {})
    assert "API Key" not in (tx.metadata or {})
    assert "secret-user" not in str(tx.metadata)
    assert "abc123" not in str(tx.metadata)


# 30. no float conversion
def test_no_float_conversion():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000.123456789",
            "Amount": "0.123456789012345",
            "Total": "3700.123456789",
            "Fee": "0.000000000123456",
            "Fee Coin": "BNB",
        }
    ]
    result = adapter.adapt(rows)
    tx = result.transactions[0]
    assert isinstance(tx.quantity, Decimal)
    assert isinstance(tx.price, Decimal)
    assert isinstance(tx.value, Decimal)
    assert isinstance(tx.fee, Decimal)
    assert tx.quantity == Decimal("0.123456789012345")
    assert tx.price == Decimal("30000.123456789")
    assert tx.value == Decimal("3700.123456789")
    assert tx.fee == Decimal("0.000000000123456")


# 31. multiple trades same timestamp
def test_multiple_trades_same_timestamp():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
        },
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "ETH/USDT",
            "Type": "Buy",
            "Order Price": "2000",
            "Amount": "0.5",
            "Total": "1000",
        },
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 2
    assert result.transactions[0].timestamp == result.transactions[1].timestamp


# 32. repeated identical rows
def test_repeated_identical_rows():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
        },
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
        },
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 2
    assert result.transactions[0].transaction_id == result.transactions[1].transaction_id


# 33. pipeline integration spot trade history
def test_pipeline_integration_spot_trade_history():
    pipeline = _pipeline()
    result = pipeline.process_csv_content(VALID_CSV, "UTC", filename="binance_spot_trades.csv")
    assert result.source == "binance"
    assert result.report_type == "spot_trade_history"
    assert result.transaction_count == 10
    trades = [t for t in result.transactions if t.transaction_type == TransactionType.TRADE]
    assert len(trades) == 10
    assert result.summary.trades == 10


# 34. API process spot trade history
def test_api_process_spot_trade_history():
    client = TestClient(app)
    files = {"file": ("binance_spot_trades.csv", io.BytesIO(VALID_CSV.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/process?timezone=UTC", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "binance"
    assert data["report_type"] == "spot_trade_history"
    assert data["transaction_count"] == 10
    assert data["summary"]["trades"] == 10


# 35. alternative column names
def test_alternative_column_names():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Symbol": "ETH/USDT",
            "Side": "Buy",
            "Price": "2000",
            "Executed": "0.5",
            "Amount": "1000",
            "Fee": "0.2",
            "Fee Coin": "BNB",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    assert result.transactions[0].asset == "ETH"
    assert result.transactions[0].quantity == Decimal("0.5")
    assert result.transactions[0].value == Decimal("1000")


# 36. summary trade count
def test_summary_trade_count():
    pipeline = _pipeline()
    result = pipeline.process_csv_content(VALID_CSV, "UTC")
    assert result.summary.trades == 10


# 37. valid decimal fee remains unchanged
def test_valid_decimal_fee_unchanged():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
            "Fee": "0.1",
            "Fee Coin": "BNB",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    assert result.transactions[0].fee == Decimal("0.1")
    assert result.transactions[0].fee_asset == "BNB"


# 38. valid fee with separate fee asset remains unchanged
def test_valid_fee_with_separate_fee_asset():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "ETH/USDT",
            "Type": "Sell",
            "Price": "2000",
            "Quantity": "0.5",
            "Amount": "1000",
            "Fee": "0.2",
            "Fee Coin": "USDT",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    assert result.transactions[0].fee == Decimal("0.2")
    assert result.transactions[0].fee_asset == "USDT"


# 39. malformed fee does not silently disappear
def test_malformed_fee_rejected():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
            "Fee": "not_a_number",
            "Fee Coin": "BNB",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 0
    assert len(result.errors) == 1
    assert "Invalid fee value" in result.errors[0]


# 40. NaN fee rejected
def test_nan_fee_rejected():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
            "Fee": "NaN",
            "Fee Coin": "BNB",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 0
    assert len(result.errors) == 1
    assert "Fee is NaN or infinite" in result.errors[0]


# 41. asset equals quote_asset rejected
def test_asset_equals_quote_asset_rejected():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/BTC",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 0
    assert len(result.errors) == 1
    assert "asset and quote_asset must differ" in result.errors[0]


# 42. BTC/USDT remains valid
def test_btc_usdt_remains_valid():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    assert result.transactions[0].asset == "BTC"
    assert result.transactions[0].quote_asset == "USDT"


# 43. unknown symbol continues existing behavior
def test_unknown_symbol_continues_existing_behavior():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "XYZABC",
            "Type": "Buy",
            "Order Price": "100",
            "Amount": "1",
            "Total": "100",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    assert result.transactions[0].asset == "XYZABC"
    assert result.transactions[0].quote_asset is None
    assert any("Unable to resolve Pair" in w for w in result.warnings)


# 44. ambiguous symbol continues existing behavior
def test_ambiguous_symbol_continues_existing_behavior():
    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTCUSDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    assert result.transactions[0].asset == "BTC"
    assert result.transactions[0].quote_asset == "USDT"


def test_spot_buy_not_a_transfer_leg():
    from backend.reconciliation.transfers import TransferReconciler

    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
        }
    ]
    result = adapter.adapt(rows)
    tx = result.transactions[0]
    assert tx.transaction_type == TransactionType.TRADE
    reconciler = TransferReconciler()
    transfer_result = reconciler.reconcile([tx])
    assert len(transfer_result.matches) == 0
    assert len(transfer_result.unmatched_leg_ids) == 0


def test_spot_sell_not_a_transfer_leg():
    from backend.reconciliation.transfers import TransferReconciler

    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Sell",
            "Order Price": "31000",
            "Amount": "0.01",
            "Total": "310",
        }
    ]
    result = adapter.adapt(rows)
    tx = result.transactions[0]
    assert tx.transaction_type == TransactionType.TRADE
    reconciler = TransferReconciler()
    transfer_result = reconciler.reconcile([tx])
    assert len(transfer_result.matches) == 0
    assert len(transfer_result.unmatched_leg_ids) == 0


def test_spot_buy_not_a_convert_leg():
    from backend.reconciliation.converts import ConvertReconciler

    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
        }
    ]
    result = adapter.adapt(rows)
    tx = result.transactions[0]
    assert tx.transaction_type == TransactionType.TRADE
    reconciler = ConvertReconciler()
    convert_result = reconciler.reconcile([tx])
    assert len(convert_result.matches) == 0
    assert len(convert_result.unresolved_leg_ids) == 0


def test_spot_sell_not_a_convert_leg():
    from backend.reconciliation.converts import ConvertReconciler

    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Sell",
            "Order Price": "31000",
            "Amount": "0.01",
            "Total": "310",
        }
    ]
    result = adapter.adapt(rows)
    tx = result.transactions[0]
    assert tx.transaction_type == TransactionType.TRADE
    reconciler = ConvertReconciler()
    convert_result = reconciler.reconcile([tx])
    assert len(convert_result.matches) == 0
    assert len(convert_result.unresolved_leg_ids) == 0


def test_spot_trade_duplicate_detection_still_works():
    from backend.reconciliation.duplicates import DuplicateDetector, DuplicateClassification

    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
        }
    ]
    r1 = adapter.adapt(rows)
    r2 = adapter.adapt(rows)
    assert r1.transactions[0].transaction_id == r2.transactions[0].transaction_id
    detector = DuplicateDetector()
    dup_result = detector.detect([r1.transactions[0], r2.transactions[0]])
    assert len(dup_result.groups) == 1
    assert dup_result.groups[0].classification == DuplicateClassification.EXACT_DUPLICATE


def test_spot_trade_comment_engine_no_fabricated_comments():
    from backend.processing.comments import CommentEngine

    adapter = _adapter()
    rows = [
        {
            "Date(UTC)": "2024-01-01 12:00:00",
            "Pair": "BTC/USDT",
            "Type": "Buy",
            "Order Price": "30000",
            "Amount": "0.01",
            "Total": "300",
        }
    ]
    result = adapter.adapt(rows)
    engine = CommentEngine()
    comment_result = engine.process(result.transactions)
    assert len(comment_result.comments) == 0


def test_api_spot_trade_history_reconciliation_boundary():
    client = TestClient(app)
    csv_content = """Date(UTC),Pair,Type,Order Price,Amount,Average Price,Filled,Total,Fee,Fee Coin
2024-01-01 12:00:00,BTC/USDT,Buy,30000,0.01,30000,0.01,300,0.1,BNB
2024-01-02 12:00:00,ETH/USDT,Sell,2100,0.5,2100,0.5,1050,0.2,USDT
"""
    files = {"file": ("binance_spot_trades.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/process?timezone=UTC", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "binance"
    assert data["report_type"] == "spot_trade_history"
    assert data["transaction_count"] == 2
    assert data["summary"]["trades"] == 2
    assert len(data["transfer_matches"]["matches"]) == 0
    assert len(data["convert_matches"]["matches"]) == 0


# 45. real format detection
REAL_SPOT_TRADE_HISTORY_CSV = """Time,Pair,Side,Price,Executed,Amount,Fee
11/27/2022 18:34,ALPINEUSDT,SELL,2.6329,4.17ALPINE,10.979193USDT,0.01097919USDT
11/27/2022 19:00,TRXUSDT,Buy,0.05,1000TRX,50USDT,0.01USDT
"""


def test_real_format_detected_as_spot_trade_history():
    adapter = _adapter()
    rows = [
        {
            "Time": "11/27/2022 18:34",
            "Pair": "ALPINEUSDT",
            "Side": "SELL",
            "Price": "2.6329",
            "Executed": "4.17ALPINE",
            "Amount": "10.979193USDT",
            "Fee": "0.01097919USDT",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    tx = result.transactions[0]
    assert tx.transaction_type == TransactionType.TRADE
    assert tx.side == Side.SELL
    assert tx.asset == "ALPINE"
    assert tx.quantity == Decimal("4.17")
    assert tx.price == Decimal("2.6329")
    assert tx.value == Decimal("10.979193")
    assert tx.fee == Decimal("0.01097919")
    assert tx.fee_asset == "USDT"
    assert tx.quote_asset == "USDT"


def test_real_format_slash_pair():
    adapter = _adapter()
    rows = [
        {
            "Time": "11/27/2022 18:34",
            "Pair": "BTC/USDT",
            "Side": "BUY",
            "Price": "30000",
            "Executed": "0.01BTC",
            "Amount": "300USDT",
            "Fee": "0.1BNB",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    tx = result.transactions[0]
    assert tx.asset == "BTC"
    assert tx.quote_asset == "USDT"
    assert tx.quantity == Decimal("0.01")
    assert tx.value == Decimal("300")
    assert tx.fee == Decimal("0.1")
    assert tx.fee_asset == "BNB"


def test_real_format_bom_handling():
    import tempfile
    import os

    csv_with_bom = "\ufeffTime,Pair,Side,Price,Executed,Amount,Fee\n11/27/2022 18:34,ALPINEUSDT,SELL,2.6329,4.17ALPINE,10.979193USDT,0.01097919USDT\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8-sig") as f:
        f.write(csv_with_bom)
        path = f.name
    try:
        pipeline = ProcessingPipeline()
        result = pipeline.process_file(path, "UTC")
        assert result.transaction_count == 1
        assert result.source == "binance"
        assert result.report_type == "spot_trade_history"
    finally:
        os.remove(path)


def test_real_format_pipeline_integration():
    pipeline = _pipeline()
    result = pipeline.process_csv_content(REAL_SPOT_TRADE_HISTORY_CSV, "UTC")
    assert result.transaction_count == 2
    assert result.source == "binance"
    assert result.report_type == "spot_trade_history"
    trades = [t for t in result.transactions if t.transaction_type == TransactionType.TRADE]
    assert len(trades) == 2


def test_real_format_api():
    client = TestClient(app)
    files = {"file": ("real_spot_trades.csv", io.BytesIO(REAL_SPOT_TRADE_HISTORY_CSV.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/process?timezone=UTC", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "binance"
    assert data["report_type"] == "spot_trade_history"
    assert data["transaction_count"] == 2


def test_real_format_quantity_value_relationship():
    adapter = _adapter()
    rows = [
        {
            "Time": "11/27/2022 18:34",
            "Pair": "ALPINEUSDT",
            "Side": "SELL",
            "Price": "2.6329",
            "Executed": "4.17ALPINE",
            "Amount": "10.979193USDT",
            "Fee": "0.01097919USDT",
        }
    ]
    result = adapter.adapt(rows)
    assert len(result.transactions) == 1
    tx = result.transactions[0]
    expected_value = tx.quantity * tx.price
    assert tx.value == expected_value
