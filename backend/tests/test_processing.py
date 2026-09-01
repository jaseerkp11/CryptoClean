import io

import pytest
from fastapi.testclient import TestClient

from backend.models.transaction import TransactionType
from backend.processing.pipeline import ProcessingPipeline
from backend.processing.models import ProcessingResult
from backend.main import app

BINANCE_CSV = """User ID,Time,Account,Operation,Coin,Change,Remark
REDACTED,2024-10-20 21:01:19,Spot,Deposit,SOL,+0.0215519,
REDACTED,2024-10-20 21:01:19,Spot,Binance Convert,USDT,+3.42578053
REDACTED,2024-10-20 21:01:19,Spot,Binance Convert,SOL,-0.0215519
REDACTED,2024-10-20 21:02:00,USD-M Futures,Transfer Between Spot and UM Futures,USDT,-1.90294738
REDACTED,2024-10-20 21:02:00,Spot,Transfer Between Spot and UM Futures,USDT,+1.90294738
REDACTED,2024-10-20 21:04:00,USD-M Futures,Fee,USDT,-0.0119187,TradeID - 14707925
REDACTED,2024-10-20 21:05:00,USD-M Futures,Funding Fee,USDT,-0.0011924
REDACTED,2024-10-20 21:06:00,USD-M Futures,Realized Profit and Loss,USDT,-0.3519
REDACTED,2024-10-20 21:07:00,Funding,P2P Trading,USDT,+21.57
REDACTED,2024-10-20 21:08:00,Funding,Crypto Box,LINEA,+1.6
REDACTED,2024-10-20 21:10:00,Spot,Simple Earn Flexible Subscription,BTTC,-2171.4
REDACTED,2024-10-20 21:12:00,Spot,Unknown Operation,XRP,+10.0
"""


def _pipeline():
    return ProcessingPipeline()


# 1. Binance CSV → successful pipeline
def test_binance_csv_successful_pipeline():
    res = _pipeline().process_csv_content(BINANCE_CSV, "UTC")
    assert isinstance(res, ProcessingResult)
    assert res.source == "binance"
    assert res.transaction_count == 12


# 2. Canonical transactions created
def test_canonical_transactions_created():
    res = _pipeline().process_csv_content(BINANCE_CSV, "UTC")
    assert len(res.transactions) == 12


# 3. Deposit appears correctly
def test_deposit_appears():
    res = _pipeline().process_csv_content(BINANCE_CSV, "UTC")
    deposits = [t for t in res.transactions if t.transaction_type == TransactionType.DEPOSIT]
    assert len(deposits) == 1
    assert deposits[0].asset == "SOL"


# 4. Transfer pair is reconciled
def test_transfer_pair_reconciled():
    res = _pipeline().process_csv_content(BINANCE_CSV, "UTC")
    assert res.transfer_matches is not None
    assert len(res.transfer_matches.matches) == 1
    m = res.transfer_matches.matches[0]
    assert m.source_account == "USD-M Futures"
    assert m.destination_account == "Spot"
    assert m.asset == "USDT"


# 5. Duplicate findings are returned
def test_duplicate_findings_returned():
    res = _pipeline().process_csv_content(BINANCE_CSV, "UTC")
    assert res.duplicate_findings is not None
    assert res.duplicate_findings.groups == []


# 6. Unknown operation is preserved
def test_unknown_operation_preserved():
    res = _pipeline().process_csv_content(BINANCE_CSV, "UTC")
    unknowns = [t for t in res.transactions if t.transaction_type == TransactionType.UNKNOWN]
    # Binance Convert (2) + P2P Trading + Realized Profit and Loss + Unknown Operation
    assert len(unknowns) == 5


# 7. Fee appears correctly
def test_fee_appears():
    res = _pipeline().process_csv_content(BINANCE_CSV, "UTC")
    fees = [t for t in res.transactions if t.transaction_type == TransactionType.FEE]
    assert len(fees) == 2


# 8. User ID is not returned
def test_user_id_not_returned():
    res = _pipeline().process_csv_content(BINANCE_CSV, "UTC")
    assert "REDACTED" not in str(res)


# 9. User ID is not stored in canonical metadata
def test_user_id_not_stored_in_metadata():
    res = _pipeline().process_csv_content(BINANCE_CSV, "UTC")
    for tx in res.transactions:
        assert "User ID" not in (tx.metadata or {})


# 10. Missing timezone defaults to UTC for naive timestamps
def test_missing_timezone_defaults_to_utc():
    res = _pipeline().process_csv_content(BINANCE_CSV, None)
    assert res.transaction_count == 12
    assert not res.errors


# 11. Explicit timezone accepted
def test_explicit_timezone_accepted():
    res = _pipeline().process_csv_content(BINANCE_CSV, "UTC")
    assert res.transaction_count == 12


# 12. Invalid timezone rejected
def test_invalid_timezone_rejected():
    res = _pipeline().process_csv_content(BINANCE_CSV, "Not/A_Timezone")
    assert res.transaction_count == 0
    assert any("Invalid timezone" in e for e in res.errors)


# 13. Unknown exchange handled correctly
def test_unknown_exchange_handled():
    unknown_csv = "foo,bar,baz\n1,2,3\n"
    res = _pipeline().process_csv_content(unknown_csv, "UTC", filename="random_file.csv")
    assert res.source == "unknown"
    assert any("Unsupported or unknown source" in e for e in res.errors)


# 14. Unsupported exchange handled correctly
def test_unsupported_exchange_handled():
    unknown_csv = (
        "Foo,Bar,Baz\n"
        "1,2,3\n"
    )
    res = _pipeline().process_csv_content(
        unknown_csv, "UTC", filename="unknown_exchange.csv"
    )
    assert res.source == "unknown"
    assert any("Unsupported or unknown source" in e for e in res.errors)


# 15. malformed CSV handled
def test_malformed_csv_handled():
    res = _pipeline().process_csv_content("this is not a valid csv at all", "UTC")
    assert res.transaction_count == 0
    assert len(res.errors) > 0


# 16. pipeline does not delete transactions
def test_pipeline_does_not_delete_transactions():
    res = _pipeline().process_csv_content(BINANCE_CSV, "UTC")
    # 12 source rows -> 12 canonical transactions, nothing dropped.
    assert res.transaction_count == 12
    assert len(res.transactions) == 12


# 17. duplicate findings remain separate
def test_duplicate_findings_separate():
    res = _pipeline().process_csv_content(BINANCE_CSV, "UTC")
    # Findings are a separate object; transactions list is untouched.
    assert res.duplicate_findings is not None
    assert len(res.transactions) == 12


# 18. transfer findings remain separate
def test_transfer_findings_separate():
    res = _pipeline().process_csv_content(BINANCE_CSV, "UTC")
    assert res.transfer_matches is not None
    assert len(res.transactions) == 12


# 19. summary counts correct
def test_summary_counts_correct():
    res = _pipeline().process_csv_content(BINANCE_CSV, "UTC")
    s = res.summary
    assert s.total_transactions == 12
    assert s.deposits == 1
    assert s.withdrawals == 0
    assert s.transfers == 3  # 2 transfer legs + 1 Earn subscription
    assert s.fees == 2
    assert s.internal_transfers == 1
    assert s.duplicate_groups == 0
    assert s.unknown_transactions == 5


def test_api_process_endpoint():
    client = TestClient(app)
    files = {"file": ("binance_export.csv", io.BytesIO(BINANCE_CSV.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/process?timezone=UTC", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "binance"
    assert data["transaction_count"] == 12
    assert len(data["transfer_matches"]["matches"]) == 1


def test_api_process_missing_timezone():
    client = TestClient(app)
    files = {"file": ("binance_export.csv", io.BytesIO(BINANCE_CSV.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/process", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "binance"
    assert data["transaction_count"] == 12


def test_mixed_source_spot_and_transaction_record_isolation():
    transaction_record_csv = """User ID,Time,Account,Operation,Coin,Change,Remark
REDACTED,2024-10-20 21:01:19,Spot,Deposit,SOL,+0.0215519,
REDACTED,2024-10-20 21:02:00,Spot,Transfer Between Spot and UM Futures,USDT,-1.90294738
REDACTED,2024-10-20 21:02:00,USD-M Futures,Transfer Between Spot and UM Futures,USDT,+1.90294738
REDACTED,2024-10-20 21:04:00,USD-M Futures,Fee,USDT,-0.0119187,TradeID - 14707925
REDACTED,2024-10-20 21:06:00,USD-M Futures,Realized Profit and Loss,USDT,-0.3519
REDACTED,2024-10-20 21:10:00,Spot,Simple Earn Flexible Subscription,BTTC,-2171.4
REDACTED,2024-10-20 21:12:00,Spot,Unknown Operation,XRP,+10.0
"""
    spot_trade_csv = """Date(UTC),Pair,Type,Order Price,Amount,Average Price,Filled,Total,Fee,Fee Coin
2024-01-01 12:00:00,BTC/USDT,Buy,30000,0.01,30000,0.01,300,0.1,BNB
2024-01-02 12:00:00,ETH/USDT,Sell,2100,0.5,2100,0.5,1050,0.2,USDT
"""
    pipeline = _pipeline()
    tr_result = pipeline.process_csv_content(transaction_record_csv, "UTC")
    spot_result = pipeline.process_csv_content(spot_trade_csv, "UTC")
    all_transactions = tr_result.transactions + spot_result.transactions
    trades = [t for t in all_transactions if t.transaction_type == TransactionType.TRADE]
    spot_transfers = [t for t in spot_result.transactions if t.transaction_type == TransactionType.TRANSFER]
    spot_unknowns = [t for t in spot_result.transactions if t.transaction_type == TransactionType.UNKNOWN]
    assert len(trades) == 2
    assert len(spot_transfers) == 0
    assert len(spot_unknowns) == 0


def test_coinbase_swap_in_summary():
    csv_content = "Timestamp,Transaction Type,Asset,Quantity Transacted,Spot Price Currency,Spot Price at Transaction,Subtotal,Total (inclusive of fees),Fees,Notes\n"
    csv_content += "2024-01-01 00:00:00 UTC,Convert,BTC,0.01,USD,30000,300,300.5,0.5,swap btc to eth\n"
    csv_content += "2024-01-01 00:00:00 UTC,Convert,ETH,0.5,USD,600,300,300.5,0.5,swap btc to eth\n"
    pipeline = _pipeline()
    result = pipeline.process_csv_content(csv_content, "UTC")
    assert result.summary.swaps == 2
    assert result.summary.unknown_transactions == 0
    assert result.summary.trades == 0


def test_timezone_aware_binance_timestamps_process_without_manual_timezone():
    csv_content = "User ID,Time,Account,Operation,Coin,Change,Remark\n"
    csv_content += "REDACTED,2022-01-15 12:00:00+05:00,Spot,Deposit,BTC,+0.01,\n"
    csv_content += "REDACTED,2022-06-20 08:30:00+00:00,Spot,Trade,BTC,-0.01,TradeID - 1\n"
    pipeline = _pipeline()
    result = pipeline.process_csv_content(csv_content, None)
    assert result.transaction_count == 2
    assert result.source == "binance"
    assert not result.errors


def test_naive_binance_timestamps_default_to_utc():
    csv_content = "User ID,Time,Account,Operation,Coin,Change,Remark\n"
    csv_content += "REDACTED,2022-01-15 12:00:00,Spot,Deposit,BTC,+0.01,\n"
    pipeline = _pipeline()
    result = pipeline.process_csv_content(csv_content, None, plan="standard")
    assert result.transaction_count == 1
    assert result.source == "binance"
    assert result.transactions[0].timestamp.tzinfo is not None


def test_free_plan_enforces_100_transaction_limit():
    rows = "\n".join([f"REDACTED,2024-01-01 12:00:00,Spot,Deposit,BTC,+0.01," for _ in range(101)])
    csv_content = "User ID,Time,Account,Operation,Coin,Change,Remark\n" + rows
    pipeline = _pipeline()
    result = pipeline.process_csv_content(csv_content, "UTC", plan="free")
    assert result.transaction_count == 0
    assert any("100 transactions" in e for e in result.errors)


def test_standard_plan_allows_up_to_5000_transactions():
    rows = "\n".join([f"REDACTED,2024-01-01 12:00:00,Spot,Deposit,BTC,+0.01," for _ in range(10)])
    csv_content = "User ID,Time,Account,Operation,Coin,Change,Remark\n" + rows
    pipeline = _pipeline()
    result = pipeline.process_csv_content(csv_content, "UTC", plan="standard")
    assert result.transaction_count == 10


def test_standard_plan_rejects_over_limit():
    rows = "\n".join([f"REDACTED,2024-01-01 12:00:00,Spot,Deposit,BTC,+0.01," for _ in range(5001)])
    csv_content = "User ID,Time,Account,Operation,Coin,Change,Remark\n" + rows
    pipeline = _pipeline()
    result = pipeline.process_csv_content(csv_content, "UTC", plan="standard")
    assert result.transaction_count == 0
    assert any("5000 transactions" in e for e in result.errors)


def test_complete_plan_allows_large_files():
    rows = "\n".join([f"REDACTED,2024-01-01 12:00:00,Spot,Deposit,BTC,+0.01," for _ in range(10)])
    csv_content = "User ID,Time,Account,Operation,Coin,Change,Remark\n" + rows
    pipeline = _pipeline()
    result = pipeline.process_csv_content(csv_content, "UTC", plan="complete")
    assert result.transaction_count == 10
