import csv
import io
import pytest
from fastapi.testclient import TestClient
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from backend.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "CryptoClean"


def test_valid_csv_ingestion():
    csv_content = "Date(UTC),Pair,Type,Order Price,Amount,Average Price,Filled,Total,Fee,Fee Coin\n"
    csv_content += "2024-01-01,BTC/USDT,Buy,30000,0.01,30000,0.01,300,0.1,BNB\n"
    csv_content += "2024-01-02,BTC/USDT,Sell,31000,0.01,31000,0.01,310,0.1,BNB\n"
    files = {"file": ("binance_export.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/ingest", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["rows"] == 2
    assert data["columns"] == 10
    assert data["exchange"] == "binance"


def test_empty_csv():
    csv_content = ""
    files = {"file": ("empty.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/ingest", files=files)
    assert response.status_code == 400


def test_invalid_extension():
    files = {"file": ("data.txt", io.BytesIO(b"hello"), "text/plain")}
    response = client.post("/api/v1/ingest", files=files)
    assert response.status_code == 400


def test_malformed_csv():
    csv_content = "Date(UTC),Pair,Type\n"
    csv_content += "2024-01-01,BTC/USDT\n"
    csv_content += "2024-01-02,BTC/USDT,Sell,extra,fields\n"
    files = {"file": ("bad.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/ingest", files=files)
    assert response.status_code == 400


def test_unknown_exchange():
    csv_content = "Col1,Col2,Col3\n1,2,3\n4,5,6\n"
    files = {"file": ("random.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/ingest", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["exchange"] == "unknown"
    assert data["confidence"] == 0.0


def test_synthetic_binance_detection():
    csv_content = "Date(UTC),Pair,Type,Order Price,Amount,Average Price,Filled,Total,Fee,Fee Coin\n"
    csv_content += "2024-01-01,BTC/USDT,Buy,30000,0.01,30000,0.01,300,0.1,BNB\n"
    files = {"file": ("binance_trades.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/ingest", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["exchange"] == "binance"
    assert data["confidence"] > 0.0


def test_synthetic_coinbase_detection():
    csv_content = "Timestamp,Transaction Type,Asset,Quantity Transacted,Spot Price Currency,Spot Price at Transaction,Subtotal,Total (inclusive of fees),Fees,Notes\n"
    csv_content += "2024-01-01 00:00:00 UTC,Buy,BTC,0.01,USD,30000,300,300.5,0.5,coinbase purchase\n"
    files = {"file": ("coinbase_report.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/ingest", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["exchange"] == "coinbase"
    assert data["confidence"] > 0.0


def test_synthetic_bybit_detection():
    csv_content = "Exec Time,Symbol,Exec Type,Order Qty,Exec Qty,Order Price,Exec Price,Fee,Order Avg Price,Type,Subject\n"
    csv_content += "2024-01-01 00:00:00 UTC,BTCUSDT,Trade,0.01,0.01,30000,30000,0.1,30000,Limit,Spot\n"
    files = {"file": ("bybit_deposit.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/ingest", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["exchange"] == "bybit"
    assert data["confidence"] > 0.0


def test_oversized_upload():
    large_content = "a" * (51 * 1024 * 1024)
    files = {"file": ("large.csv", io.BytesIO(large_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/ingest", files=files)
    assert response.status_code == 400


def test_blank_invalid_headers():
    csv_content = ",,\n1,2,3\n"
    files = {"file": ("bad_headers.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/ingest", files=files)
    assert response.status_code == 400


def test_invalid_encoding():
    csv_content = b"\xff\xfe\xfd" + b"Date(UTC),Pair,Type\n"
    files = {"file": ("bad_encoding.csv", io.BytesIO(csv_content), "application/octet-stream")}
    response = client.post("/api/v1/ingest", files=files)
    assert response.status_code == 400


def test_csv_formula_values_preserved_in_pipeline():
    from backend.processing.pipeline import ProcessingPipeline

    csv_content = "User ID,Time,Account,Operation,Coin,Change,Remark\n"
    csv_content += "REDACTED,2024-01-01 00:00:00,Spot,Deposit,SOL,0.01,=cmd|'/c calc'!A1\n"
    pipeline = ProcessingPipeline()
    result = pipeline.process_csv_content(csv_content, "UTC")
    assert result.transaction_count == 1
    tx = result.transactions[0]
    assert tx.metadata.get("source_remark") == "=cmd|'/c calc'!A1"


def test_duplicate_column_names_rejected():
    csv_content = "Date(UTC),Pair,Type,Date(UTC)\n"
    csv_content += "2024-01-01,BTC/USDT,Buy,extra\n"
    files = {"file": ("dup_cols.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/ingest", files=files)
    assert response.status_code == 400
    data = response.json()
    assert "Duplicate column name" in data["detail"]


def test_semicolon_delimited_csv():
    csv_content = "Date(UTC);Pair;Type;Order Price;Amount\n"
    csv_content += "2024-01-01;BTC/USDT;Buy;30000;0.01\n"
    files = {"file": ("semi.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/ingest", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["exchange"] == "binance"


def test_binance_filename_without_binance_columns():
    csv_content = "Col1,Col2,Col3\n1,2,3\n"
    files = {"file": ("binance_trades.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/ingest", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["exchange"] == "unknown"
    assert data["confidence"] == 0.0


# --- Direct detector unit tests ---

import pandas as pd
from backend.ingestion.detector import detect_exchange


def test_detect_binance_spot_trade_history_strong_match():
    df = pd.DataFrame(
        {
            "Date(UTC)": ["2024-01-01"],
            "Pair": ["BTC/USDT"],
            "Type": ["Buy"],
            "Order Price": ["30000"],
            "Amount": ["0.01"],
        }
    )
    exchange, report_type, confidence, indicators, warnings = detect_exchange(
        "binance_export.csv", df, list(df.columns)
    )
    assert exchange == "binance"
    assert report_type == "spot_trade_history"
    assert confidence >= 0.55
    assert len(warnings) == 0


def test_detect_binance_transaction_record_strong_match():
    df = pd.DataFrame(
        {
            "User ID": ["REDACTED"],
            "Time": ["2024-01-01 00:00:00"],
            "Account": ["Spot"],
            "Operation": ["Deposit"],
            "Coin": ["BTC"],
            "Change": ["0.01"],
            "Remark": [""],
        }
    )
    exchange, report_type, confidence, indicators, warnings = detect_exchange(
        "binance_ledger.csv", df, list(df.columns)
    )
    assert exchange == "binance"
    assert report_type == "transaction_record"
    assert confidence >= 0.55
    assert len(warnings) == 0


def test_filename_match_insufficient_columns_rejected():
    df = pd.DataFrame({"Date(UTC)": ["2024-01-01"], "Pair": ["BTC/USDT"]})
    exchange, report_type, confidence, indicators, warnings = detect_exchange(
        "binance_trades.csv", df, list(df.columns)
    )
    assert exchange == "unknown"
    assert confidence == 0.0


def test_partial_column_overlap_unrelated_csv_rejected():
    df = pd.DataFrame({"Time": ["2024-01-01"], "Type": ["Buy"], "Amount": ["0.01"]})
    exchange, report_type, confidence, indicators, warnings = detect_exchange(
        "random.csv", df, list(df.columns)
    )
    assert exchange == "unknown"
    assert confidence == 0.0


def test_ambiguous_binance_signatures_returns_unknown():
    columns = [
        "Date(UTC)",
        "Pair",
        "Type",
        "Order Price",
        "Amount",
        "User ID",
        "Time",
        "Account",
        "Operation",
        "Coin",
        "Change",
        "Remark",
    ]
    df = pd.DataFrame({c: ["x"] for c in columns})
    exchange, report_type, confidence, indicators, warnings = detect_exchange(
        "binance_export.csv", df, list(df.columns)
    )
    assert exchange == "unknown"
    assert confidence == 0.0
    assert len(warnings) > 0
    assert any("disambiguate" in w.lower() for w in warnings)


def test_extra_columns_do_not_break_detection():
    df = pd.DataFrame(
        {
            "Date(UTC)": ["2024-01-01"],
            "Pair": ["BTC/USDT"],
            "Type": ["Buy"],
            "Order Price": ["30000"],
            "Amount": ["0.01"],
            "ExtraCol1": ["x"],
            "ExtraCol2": ["y"],
        }
    )
    exchange, report_type, confidence, indicators, warnings = detect_exchange(
        "binance_trades.csv", df, list(df.columns)
    )
    assert exchange == "binance"
    assert report_type == "spot_trade_history"


def test_column_order_does_not_affect_detection():
    df = pd.DataFrame(
        {
            "Amount": ["0.01"],
            "Date(UTC)": ["2024-01-01"],
            "Type": ["Buy"],
            "Pair": ["BTC/USDT"],
            "Order Price": ["30000"],
        }
    )
    exchange, report_type, confidence, indicators, warnings = detect_exchange(
        "binance_trades.csv", df, list(df.columns)
    )
    assert exchange == "binance"
    assert report_type == "spot_trade_history"


def test_case_whitespace_normalization():
    df = pd.DataFrame(
        {
            "DATE(UTC)": ["2024-01-01"],
            "pair ": ["BTC/USDT"],
            "  Type": ["Buy"],
            "Order Price": ["30000"],
            "Amount": ["0.01"],
        }
    )
    exchange, report_type, confidence, indicators, warnings = detect_exchange(
        "binance_trades.csv", df, list(df.columns)
    )
    assert exchange == "binance"
    assert report_type == "spot_trade_history"


def test_empty_dataframe_returns_unknown():
    df = pd.DataFrame()
    exchange, report_type, confidence, indicators, warnings = detect_exchange(
        "binance_trades.csv", df, list(df.columns)
    )
    assert exchange == "unknown"
    assert confidence == 0.0


def test_unknown_exchange_with_unrelated_columns():
    df = pd.DataFrame({"Col1": ["a"], "Col2": ["b"]})
    exchange, report_type, confidence, indicators, warnings = detect_exchange(
        "random.csv", df, list(df.columns)
    )
    assert exchange == "unknown"
    assert confidence == 0.0
