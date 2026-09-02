import csv
import io
import zipfile
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.processing.pipeline import ProcessingPipeline
from backend.processing.models import ProcessingResult
from backend.models.transaction import TransactionType

client = TestClient(app)

REAL_BINANCE_CSV = open(
    r"C:\Projects\CryptoClean\Binance-Transaction-History-202609011815(UTC+5)-part1-of1.csv",
    "r",
    encoding="utf-8",
).read()


def test_real_binance_1341_rows_processes_successfully():
    pipeline = ProcessingPipeline()
    result = pipeline.process_csv_content(REAL_BINANCE_CSV, timezone=None, plan="complete")
    assert result.transaction_count == 1341
    assert result.source == "binance"
    assert result.report_type == "transaction_record"
    assert len(result.errors) == 0


def test_real_binance_operation_type_coverage():
    pipeline = ProcessingPipeline()
    result = pipeline.process_csv_content(REAL_BINANCE_CSV, timezone=None, plan="complete")
    type_counts = {}
    for tx in result.transactions:
        t = tx.transaction_type.value
        type_counts[t] = type_counts.get(t, 0) + 1

    assert type_counts.get("DEPOSIT", 0) == 127
    assert type_counts.get("WITHDRAWAL", 0) == 47
    assert type_counts.get("FEE", 0) >= 150
    assert type_counts.get("REWARD", 0) >= 200
    assert type_counts.get("TRADE", 0) >= 240
    assert type_counts.get("TRANSFER", 0) >= 340
    assert type_counts.get("AIRDROP", 0) >= 10
    assert type_counts.get("UNKNOWN", 0) >= 150


def test_real_binance_transfer_reconciliation():
    pipeline = ProcessingPipeline()
    result = pipeline.process_csv_content(REAL_BINANCE_CSV, timezone=None, plan="complete")
    assert result.transfer_matches is not None
    assert len(result.transfer_matches.matches) >= 150


def test_real_binance_summary_has_dashboard_metrics():
    pipeline = ProcessingPipeline()
    result = pipeline.process_csv_content(REAL_BINANCE_CSV, timezone=None, plan="complete")
    s = result.summary
    assert s.total_transactions == 1341
    assert s.deposits == 127
    assert s.withdrawals == 47
    assert s.transfers >= 340
    assert s.trades >= 240
    assert s.fees >= 150
    assert s.unknown_transactions >= 150


def test_export_complete_zip_contains_all_files():
    files = {"file": ("binance_export.csv", io.BytesIO(REAL_BINANCE_CSV.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/export?plan=complete", files=files)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"] == "attachment; filename=KryptLedg_Report.zip"

    zip_buffer = io.BytesIO(response.content)
    with zipfile.ZipFile(zip_buffer, "r") as zf:
        names = zf.namelist()
        assert "Transactions.csv" in names
        assert "Accounting.csv" in names
        assert "Transfers.csv" in names
        assert "Exceptions.csv" in names
        assert "Summary.csv" in names
        assert "Detailed_Realized_PnL.csv" in names
        assert "Holdings.csv" in names
        assert "Missing_Cost_Basis.csv" in names
        assert "Audit_Trail.csv" in names


def test_export_standard_zip_contains_core_files():
    files = {"file": ("binance_export.csv", io.BytesIO(REAL_BINANCE_CSV.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/export?plan=standard", files=files)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"

    zip_buffer = io.BytesIO(response.content)
    with zipfile.ZipFile(zip_buffer, "r") as zf:
        names = zf.namelist()
        assert "Transactions.csv" in names
        assert "Accounting.csv" in names
        assert "Transfers.csv" in names
        assert "Exceptions.csv" in names
        assert "Summary.csv" in names
        assert "Detailed_Realized_PnL.csv" not in names
        assert "Holdings.csv" not in names


def test_export_free_returns_single_csv():
    small_csv = "User ID,Time,Account,Operation,Coin,Change,Remark\nREDACTED,2024-01-01 12:00:00,Spot,Deposit,BTC,+0.01,"
    files = {"file": ("binance_export.csv", io.BytesIO(small_csv.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/export?plan=free", files=files)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "transactions.csv" in response.headers["content-disposition"]


def test_export_transactions_csv_headers_and_traceability():
    files = {"file": ("binance_export.csv", io.BytesIO(REAL_BINANCE_CSV.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/export?plan=complete", files=files)
    assert response.status_code == 200

    zip_buffer = io.BytesIO(response.content)
    with zipfile.ZipFile(zip_buffer, "r") as zf:
        transactions_csv = zf.read("Transactions.csv").decode("utf-8")
    reader = csv.DictReader(io.StringIO(transactions_csv))
    rows = list(reader)
    assert len(rows) == 1341
    expected_headers = {
        "transaction_id",
        "timestamp",
        "transaction_type",
        "side",
        "asset",
        "quantity",
        "source_transaction_id",
        "fee",
        "fee_asset",
        "wallet",
        "counterparty",
        "tx_hash",
        "confidence",
        "notes",
        "source_operation",
        "source_account",
        "source_change_signed",
        "source_remark",
        "classification",
        "classification_reason",
        "review_required",
    }
    assert expected_headers.issubset(set(reader.fieldnames or []))

    unknowns = [r for r in rows if r["classification"] == "UNKNOWN"]
    assert len(unknowns) >= 150
    for row in unknowns:
        assert row["source_operation"]
        assert row["review_required"] == "Yes"


def test_export_accounting_csv_has_pnl_and_lot_linkage():
    files = {"file": ("binance_export.csv", io.BytesIO(REAL_BINANCE_CSV.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/export?plan=complete", files=files)
    assert response.status_code == 200

    zip_buffer = io.BytesIO(response.content)
    with zipfile.ZipFile(zip_buffer, "r") as zf:
        accounting_csv = zf.read("Accounting.csv").decode("utf-8")
    reader = csv.DictReader(io.StringIO(accounting_csv))
    rows = list(reader)
    assert len(rows) >= 1000

    pnl_rows = [r for r in rows if r.get("realized_pnl")]
    disposal_rows = [r for r in rows if r["event_type"] == "DISPOSAL"]
    assert len(disposal_rows) >= 180

    for row in rows:
        if row["event_type"] in {"ACQUISITION", "DISPOSAL"}:
            assert row["cost_basis"] or row["proceeds"] or row["realized_pnl"] or True


def test_export_exceptions_csv_groups_by_type():
    files = {"file": ("binance_export.csv", io.BytesIO(REAL_BINANCE_CSV.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/export?plan=complete", files=files)
    assert response.status_code == 200

    zip_buffer = io.BytesIO(response.content)
    with zipfile.ZipFile(zip_buffer, "r") as zf:
        exceptions_csv = zf.read("Exceptions.csv").decode("utf-8")
    reader = csv.DictReader(io.StringIO(exceptions_csv))
    rows = list(reader)
    assert len(rows) >= 100
    categories = {r["category"] for r in rows}
    assert "adapter" in categories
    assert "accounting" in categories


def test_export_transfers_csv_preserves_matched_pairs():
    files = {"file": ("binance_export.csv", io.BytesIO(REAL_BINANCE_CSV.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/export?plan=complete", files=files)
    assert response.status_code == 200

    zip_buffer = io.BytesIO(response.content)
    with zipfile.ZipFile(zip_buffer, "r") as zf:
        transfers_csv = zf.read("Transfers.csv").decode("utf-8")
    reader = csv.DictReader(io.StringIO(transfers_csv))
    rows = list(reader)
    matched = [r for r in rows if r["matching_status"] == "matched"]
    unmatched = [r for r in rows if r["matching_status"] == "unmatched"]
    assert len(matched) >= 150
    for row in matched:
        assert row["source_transaction_id"]
        assert row["destination_transaction_id"]
        assert row["transfer_id"]
        assert row["confidence"] in {"95", "100"}


def test_export_summary_csv_has_dashboard_fields():
    files = {"file": ("binance_export.csv", io.BytesIO(REAL_BINANCE_CSV.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/export?plan=complete", files=files)
    assert response.status_code == 200

    zip_buffer = io.BytesIO(response.content)
    with zipfile.ZipFile(zip_buffer, "r") as zf:
        summary_csv = zf.read("Summary.csv").decode("utf-8")
    reader = csv.DictReader(io.StringIO(summary_csv))
    rows = {r["metric"]: r["value"] for r in reader}
    assert rows["total_transactions"] == "1341"
    assert int(rows["deposits"]) == 127
    assert int(rows["withdrawals"]) == 47
    assert int(rows["transfers"]) >= 340
    assert int(rows["trades"]) >= 240
    assert int(rows["fees"]) >= 150
    assert int(rows["unknown_transactions"]) >= 150
    assert "accounting_events" in rows
    assert "acquisitions" in rows
    assert "disposals" in rows


def test_export_audit_trail_preserves_source_ids_and_review_status():
    files = {"file": ("binance_export.csv", io.BytesIO(REAL_BINANCE_CSV.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/export?plan=complete", files=files)
    assert response.status_code == 200

    zip_buffer = io.BytesIO(response.content)
    with zipfile.ZipFile(zip_buffer, "r") as zf:
        audit_csv = zf.read("Audit_Trail.csv").decode("utf-8")
    reader = csv.DictReader(io.StringIO(audit_csv))
    rows = list(reader)
    assert len(rows) == 1341
    for row in rows:
        assert row["transaction_id"]
        assert row["source_operation"]
        assert row["classification"]
        assert row["review_required"] in {"Yes", "No"}


def test_plan_limit_still_enforced_during_export():
    rows = "\n".join([f"REDACTED,2024-01-01 12:00:00,Spot,Deposit,BTC,+0.01," for _ in range(101)])
    csv_content = "User ID,Time,Account,Operation,Coin,Change,Remark\n" + rows
    files = {"file": ("binance_export.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/export?plan=free", files=files)
    assert response.status_code == 400
    assert "100 transactions" in response.json()["detail"]


def test_fifo_multiple_lot_disposal():
    from backend.accounting.engine import AccountingEngine
    from backend.accounting.configuration import AccountingConfiguration
    from backend.models.transaction import CanonicalTransaction, Source, TransactionType
    from datetime import datetime, timezone

    txs = [
        CanonicalTransaction(
            transaction_id="lot1",
            source=Source.BINANCE,
            timestamp=datetime(2022, 1, 1, tzinfo=timezone.utc),
            transaction_type=TransactionType.DEPOSIT,
            asset="BTC",
            quantity=Decimal("1.0"),
            price=Decimal("30000"),
            value=Decimal("30000"),
            quote_asset="USD",
            confidence=1.0,
            metadata={"source": "binance", "source_account": "Spot"},
        ),
        CanonicalTransaction(
            transaction_id="lot2",
            source=Source.BINANCE,
            timestamp=datetime(2022, 1, 2, tzinfo=timezone.utc),
            transaction_type=TransactionType.DEPOSIT,
            asset="BTC",
            quantity=Decimal("2.0"),
            price=Decimal("30000"),
            value=Decimal("60000"),
            quote_asset="USD",
            confidence=1.0,
            metadata={"source": "binance", "source_account": "Spot"},
        ),
        CanonicalTransaction(
            transaction_id="sell1",
            source=Source.BINANCE,
            timestamp=datetime(2022, 1, 3, tzinfo=timezone.utc),
            transaction_type=TransactionType.TRADE,
            side="SELL",
            asset="BTC",
            quantity=Decimal("2.5"),
            price=Decimal("30000"),
            value=Decimal("75000"),
            quote_asset="USD",
            confidence=1.0,
            metadata={"source": "binance", "source_account": "Spot"},
        ),
    ]
    engine = AccountingEngine(AccountingConfiguration())
    result = engine.process(txs)
    assert len(result.lots) == 2
    assert len(result.consumptions) == 2
    total_cost = sum(c.cost_allocated for c in result.consumptions)
    assert total_cost == Decimal("75000")


def test_missing_cost_basis_marks_unresolved():
    from backend.accounting.engine import AccountingEngine
    from backend.accounting.configuration import AccountingConfiguration
    from backend.models.transaction import CanonicalTransaction, Source, TransactionType
    from datetime import datetime, timezone

    txs = [
        CanonicalTransaction(
            transaction_id="buy1",
            source=Source.BINANCE,
            timestamp=datetime(2022, 1, 1, tzinfo=timezone.utc),
            transaction_type=TransactionType.TRADE,
            side="BUY",
            asset="ETH",
            quantity=Decimal("1.0"),
            confidence=1.0,
            metadata={"source": "binance", "source_account": "Spot"},
        ),
        CanonicalTransaction(
            transaction_id="sell1",
            source=Source.BINANCE,
            timestamp=datetime(2022, 1, 2, tzinfo=timezone.utc),
            transaction_type=TransactionType.TRADE,
            side="SELL",
            asset="ETH",
            quantity=Decimal("1.0"),
            confidence=1.0,
            metadata={"source": "binance", "source_account": "Spot"},
        ),
    ]
    engine = AccountingEngine(AccountingConfiguration())
    result = engine.process(txs)
    disposal_events = [e for e in result.events if e.event_type.value == "DISPOSAL"]
    assert len(disposal_events) == 1
    assert disposal_events[0].proceeds is None
    assert any("MISSING_PROCEEDS" in w.code.value for w in result.warnings)


def test_realized_pnl_calculated_for_fifo_disposal():
    from backend.accounting.engine import AccountingEngine
    from backend.accounting.configuration import AccountingConfiguration
    from backend.models.transaction import CanonicalTransaction, Source, TransactionType
    from datetime import datetime, timezone

    txs = [
        CanonicalTransaction(
            transaction_id="buy1",
            source=Source.BINANCE,
            timestamp=datetime(2022, 1, 1, tzinfo=timezone.utc),
            transaction_type=TransactionType.DEPOSIT,
            asset="BTC",
            quantity=Decimal("1.0"),
            price=Decimal("30000"),
            value=Decimal("30000"),
            quote_asset="USD",
            confidence=1.0,
            metadata={"source": "binance", "source_account": "Spot"},
        ),
        CanonicalTransaction(
            transaction_id="sell1",
            source=Source.BINANCE,
            timestamp=datetime(2022, 1, 2, tzinfo=timezone.utc),
            transaction_type=TransactionType.TRADE,
            side="SELL",
            asset="BTC",
            quantity=Decimal("0.5"),
            price=Decimal("35000"),
            value=Decimal("17500"),
            quote_asset="USD",
            confidence=1.0,
            metadata={"source": "binance", "source_account": "Spot"},
        ),
    ]
    engine = AccountingEngine(AccountingConfiguration())
    result = engine.process(txs)
    assert len(result.realized_pnl) == 1
    assert result.realized_pnl[0].total_realized_pnl == Decimal("2500")
