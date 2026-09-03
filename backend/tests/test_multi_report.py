import io
import tempfile
import os
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.adapters.binance.transaction_record import BinanceTransactionRecordAdapter
from backend.adapters.binance.spot_trade_history import BinanceSpotTradeHistoryAdapter
from backend.processing.pipeline import ProcessingPipeline
from backend.processing.capabilities import (
    get_report_capabilities,
    get_report_priority,
    compute_readiness,
    REPORT_CAPABILITIES,
    REPORT_PRIORITY,
)
from backend.main import app

BINANCE_TRANSACTION_RECORD_CSV = """User ID,Time,Account,Operation,Coin,Change,Remark
REDACTED,2024-01-01 12:00:00,Spot,Deposit,BTC,0.01,
REDACTED,2024-01-02 12:00:00,Spot,Transaction Buy,BTC,-0.01,TradeID - trade-123
REDACTED,2024-01-03 12:00:00,Spot,Transaction Sold,BTC,0.005,TradeID - trade-456
REDACTED,2024-01-04 12:00:00,Spot,Withdraw,BTC,0.002,
REDACTED,2024-01-05 12:00:00,Spot,Fee,BTC,-0.0001,
"""

BINANCE_SPOT_TRADE_HISTORY_CSV = """Date(UTC),Pair,Type,Order Price,Amount,Average Price,Filled,Total,Fee,Fee Coin,Trade ID
2024-01-02 12:00:00,BTC/USDT,Buy,30000,0.01,30000,0.01,300,0.1,BNB,trade-123
2024-01-03 12:00:00,BTC/USDT,Sell,31000,0.005,31000,0.005,155,0.05,BNB,trade-456
2024-01-06 12:00:00,ETH/USDT,Buy,2000,0.5,2000,0.5,1000,0.2,BNB,
"""

COINBASE_TRANSACTION_RECORD_CSV = """Timestamp,Transaction Type,Asset,Quantity Transacted,Spot Price Currency,Spot Price at Transaction,Subtotal,Total (inclusive of fees),Fees,Notes
2024-01-01 00:00:00 UTC,Buy,BTC,0.01,USD,30000,300,300.5,0.5,coinbase purchase
2024-01-02 00:00:00 UTC,Sell,BTC,0.005,USD,31000,155,155.5,0.5,coinbase sale
"""


def _write_temp_csv(content: str) -> str:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(content)
        return f.name


def test_binance_transaction_record_capabilities():
    caps = get_report_capabilities("binance_transaction_record")
    assert "transaction_activity" in caps
    assert "transfer_information" in caps
    assert "deposit_information" in caps
    assert "withdrawal_information" in caps
    assert "fee" in caps
    assert "trade_price" not in caps


def test_binance_spot_trade_history_capabilities():
    caps = get_report_capabilities("binance_spot_trade_history")
    assert "trade_execution" in caps
    assert "trade_price" in caps
    assert "fiat_value" in caps
    assert "fee" in caps
    assert "transaction_activity" not in caps


def test_coinbase_transaction_record_capabilities():
    caps = get_report_capabilities("coinbase_transaction_record")
    assert "transaction_activity" in caps
    assert "trade_execution" in caps
    assert "trade_price" in caps
    assert "fiat_value" in caps
    assert "fee" in caps


def test_unknown_report_type_capabilities():
    caps = get_report_capabilities("unknown_type")
    assert len(caps) == 0


def test_report_priority():
    assert get_report_priority("binance_spot_trade_history") == 1
    assert get_report_priority("coinbase_transaction_record") == 2
    assert get_report_priority("binance_transaction_record") == 3
    assert get_report_priority("unknown") == 999


def test_process_files_single_binance_transaction_record():
    path = _write_temp_csv(BINANCE_TRANSACTION_RECORD_CSV)
    try:
        pipeline = ProcessingPipeline()
        result = pipeline.process_files([path], timezone="UTC", plan="complete")
        
        assert result.transaction_count == 5
        assert result.source == "binance"
        assert len(result.reports) == 1
        assert result.reports[0].report_type == "transaction_record"
        assert result.reports[0].exchange == "binance"
    finally:
        os.remove(path)


def test_process_files_single_binance_spot_trade_history():
    path = _write_temp_csv(BINANCE_SPOT_TRADE_HISTORY_CSV)
    try:
        pipeline = ProcessingPipeline()
        result = pipeline.process_files([path], timezone="UTC", plan="complete")
        
        assert result.transaction_count == 3
        assert result.source == "binance"
        assert len(result.reports) == 1
        assert result.reports[0].report_type == "spot_trade_history"
    finally:
        os.remove(path)


def test_process_files_combined_binance_reports():
    path1 = _write_temp_csv(BINANCE_TRANSACTION_RECORD_CSV)
    path2 = _write_temp_csv(BINANCE_SPOT_TRADE_HISTORY_CSV)
    try:
        pipeline = ProcessingPipeline()
        result = pipeline.process_files([path1, path2], timezone="UTC", plan="complete")
        
        assert result.transaction_count == 8
        assert len(result.reports) == 2
        report_types = {r.report_type for r in result.reports}
        assert "spot_trade_history" in report_types
        assert "transaction_record" in report_types
    finally:
        os.remove(path1)
        os.remove(path2)


def test_process_files_cross_report_deduplication():
    path1 = _write_temp_csv(BINANCE_TRANSACTION_RECORD_CSV)
    path2 = _write_temp_csv(BINANCE_SPOT_TRADE_HISTORY_CSV)
    try:
        pipeline = ProcessingPipeline()
        result = pipeline.process_files([path1, path2], timezone="UTC", plan="complete")
        
        dup_groups = result.duplicate_findings.groups if result.duplicate_findings else []
        
        assert len(dup_groups) >= 2
        for group in dup_groups:
            assert len(group.transaction_ids) >= 2
    finally:
        os.remove(path1)
        os.remove(path2)


def test_process_files_accounting_improves_with_trade_history():
    path1 = _write_temp_csv(BINANCE_TRANSACTION_RECORD_CSV)
    path2 = _write_temp_csv(BINANCE_SPOT_TRADE_HISTORY_CSV)
    try:
        pipeline = ProcessingPipeline()
        
        result_tx_record_only = pipeline.process_files([path1], timezone="UTC", plan="complete")
        result_combined = pipeline.process_files([path1, path2], timezone="UTC", plan="complete")
        
        tx_record_disposals = [e for e in (result_tx_record_only.accounting_result.events if result_tx_record_only.accounting_result else []) if e.event_type.value == "DISPOSAL"]
        combined_disposals = [e for e in (result_combined.accounting_result.events if result_combined.accounting_result else []) if e.event_type.value == "DISPOSAL"]
        
        assert len(combined_disposals) >= len(tx_record_disposals)
    finally:
        os.remove(path1)
        os.remove(path2)


def test_process_files_readiness_status():
    path1 = _write_temp_csv(BINANCE_TRANSACTION_RECORD_CSV)
    path2 = _write_temp_csv(BINANCE_SPOT_TRADE_HISTORY_CSV)
    try:
        pipeline = ProcessingPipeline()
        result = pipeline.process_files([path1, path2], timezone="UTC", plan="complete")
        
        assert result.readiness_status is not None
        assert result.readiness_status in {"READY_FOR_REVIEW", "REVIEW_REQUIRED", "INCOMPLETE_SOURCE_DATA"}
    finally:
        os.remove(path1)
        os.remove(path2)


def test_process_files_preserves_provenance():
    path1 = _write_temp_csv(BINANCE_TRANSACTION_RECORD_CSV)
    path2 = _write_temp_csv(BINANCE_SPOT_TRADE_HISTORY_CSV)
    try:
        pipeline = ProcessingPipeline()
        result = pipeline.process_files([path1, path2], timezone="UTC", plan="complete")
        
        for tx in result.transactions:
            assert "source_file" in (tx.metadata or {})
            assert "source_report_type" in (tx.metadata or {})
    finally:
        os.remove(path1)
        os.remove(path2)


def test_process_files_mixed_exchanges_not_merged():
    path1 = _write_temp_csv(BINANCE_TRANSACTION_RECORD_CSV)
    path2 = _write_temp_csv(COINBASE_TRANSACTION_RECORD_CSV)
    try:
        pipeline = ProcessingPipeline()
        result = pipeline.process_files([path1, path2], timezone="UTC", plan="complete")
        
        sources = set(tx.source.value for tx in result.transactions)
        assert "binance" in sources
        assert "coinbase" in sources
    finally:
        os.remove(path1)
        os.remove(path2)


def test_process_files_api_endpoint():
    client = TestClient(app)
    
    files = [
        ("files", ("binance_tx_record.csv", io.BytesIO(BINANCE_TRANSACTION_RECORD_CSV.encode("utf-8")), "text/csv")),
        ("files", ("binance_spot_trades.csv", io.BytesIO(BINANCE_SPOT_TRADE_HISTORY_CSV.encode("utf-8")), "text/csv")),
    ]
    response = client.post("/api/v1/process-multi?timezone=UTC", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["transaction_count"] == 8
    assert len(data["reports"]) == 2
    assert data["readiness_status"] in {"READY_FOR_REVIEW", "REVIEW_REQUIRED", "INCOMPLETE_SOURCE_DATA"}


def test_process_files_invalid_file_reported():
    path1 = _write_temp_csv(BINANCE_TRANSACTION_RECORD_CSV)
    path2 = _write_temp_csv("col1,col2\n1,2\n")
    try:
        pipeline = ProcessingPipeline()
        result = pipeline.process_files([path1, path2], timezone="UTC", plan="complete")
        
        assert result.transaction_count > 0
        assert len(result.reports) == 2
        assert any("unsupported or unknown source" in w for w in result.warnings)
    finally:
        os.remove(path1)
        os.remove(path2)


def test_compute_readiness_no_transactions():
    status, details = compute_readiness([], warnings=[], errors=["some error"])
    assert status == "INCOMPLETE_SOURCE_DATA"
    assert details["transactions_detected"] is False


def test_compute_readiness_with_trades_and_pricing():
    from backend.models.transaction import CanonicalTransaction, Source, TransactionType
    from datetime import datetime, timezone
    
    txs = [
        CanonicalTransaction(
            transaction_id="tx1",
            source=Source.BINANCE,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            transaction_type=TransactionType.TRADE,
            side="BUY",
            asset="BTC",
            quantity=Decimal("0.01"),
            price=Decimal("30000"),
            value=Decimal("300"),
            quote_asset="USD",
            confidence=1.0,
        ),
    ]
    status, details = compute_readiness(txs)
    assert status == "READY_FOR_REVIEW"
    assert details["trade_pricing_available"] is True


def test_compute_readiness_with_warnings():
    from backend.models.transaction import CanonicalTransaction, Source, TransactionType
    from datetime import datetime, timezone
    
    txs = [
        CanonicalTransaction(
            transaction_id="tx1",
            source=Source.BINANCE,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            transaction_type=TransactionType.TRADE,
            side="BUY",
            asset="BTC",
            quantity=Decimal("0.01"),
            confidence=1.0,
        ),
    ]
    status, details = compute_readiness(txs, warnings=["some warning"])
    assert status == "REVIEW_REQUIRED"
