import csv
import io
import pytest
from fastapi.testclient import TestClient
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from backend.main import app

client = TestClient(app)


# --- M028 Production Hardening Tests ---


class TestContentTypeHardening:
    def test_missing_content_type_rejected(self):
        csv_content = "Date(UTC),Pair,Type\n2024-01-01,BTC/USDT,Buy\n"
        files = {"file": ("test.csv", io.BytesIO(csv_content.encode("utf-8")), "")}
        response = client.post("/api/v1/ingest", files=files)
        assert response.status_code == 400
        assert "Content-Type" in response.json()["detail"]

    def test_empty_content_type_rejected(self):
        csv_content = "Date(UTC),Pair,Type\n2024-01-01,BTC/USDT,Buy\n"
        files = {"file": ("test.csv", io.BytesIO(csv_content.encode("utf-8")), "")}
        response = client.post("/api/v1/ingest", files=files)
        assert response.status_code == 400

    def test_invalid_content_type_rejected(self):
        csv_content = "Date(UTC),Pair,Type\n2024-01-01,BTC/USDT,Buy\n"
        files = {"file": ("test.csv", io.BytesIO(csv_content.encode("utf-8")), "application/json")}
        response = client.post("/api/v1/ingest", files=files)
        assert response.status_code == 400
        assert "Invalid content type" in response.json()["detail"]

    def test_valid_content_type_accepted(self):
        csv_content = "Date(UTC),Pair,Type,Order Price,Amount\n2024-01-01,BTC/USDT,Buy,30000,0.01\n"
        files = {"file": ("test.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
        response = client.post("/api/v1/ingest", files=files)
        assert response.status_code == 200


class TestPathTraversalProtection:
    def test_filename_with_separator_rejected(self):
        csv_content = "Date(UTC),Pair,Type\n2024-01-01,BTC/USDT,Buy\n"
        files = {"file": ("../etc/passwd.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
        response = client.post("/api/v1/ingest", files=files)
        assert response.status_code == 400
        assert "Invalid filename" in response.json()["detail"]

    def test_filename_with_backslash_rejected(self):
        csv_content = "Date(UTC),Pair,Type\n2024-01-01,BTC/USDT,Buy\n"
        files = {"file": ("..\\windows\\system32\\test.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
        response = client.post("/api/v1/ingest", files=files)
        assert response.status_code == 400
        assert "Invalid filename" in response.json()["detail"]


class TestSecurityHeaders:
    def test_security_headers_present(self):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert response.headers.get("X-XSS-Protection") == "1; mode=block"
        assert response.headers.get("Cache-Control") == "no-store"


class TestEmptyAssetValidation:
    def test_empty_asset_rejected(self):
        from backend.models.transaction import CanonicalTransaction, TransactionType, Source, Side
        from datetime import datetime, timezone
        from decimal import Decimal

        with pytest.raises(ValueError, match="asset cannot be blank"):
            CanonicalTransaction(
                transaction_id="test-1",
                source=Source.MANUAL,
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                transaction_type=TransactionType.TRADE,
                side=Side.BUY,
                asset="",
                quantity=Decimal("0.01"),
                confidence=1.0,
            )

    def test_whitespace_asset_rejected(self):
        from backend.models.transaction import CanonicalTransaction, TransactionType, Source, Side
        from datetime import datetime, timezone
        from decimal import Decimal

        with pytest.raises(ValueError, match="asset cannot be blank"):
            CanonicalTransaction(
                transaction_id="test-2",
                source=Source.MANUAL,
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                transaction_type=TransactionType.TRADE,
                side=Side.BUY,
                asset="   ",
                quantity=Decimal("0.01"),
                confidence=1.0,
            )

    def test_valid_asset_accepted(self):
        from backend.models.transaction import CanonicalTransaction, TransactionType, Source, Side
        from datetime import datetime, timezone
        from decimal import Decimal

        tx = CanonicalTransaction(
            transaction_id="test-3",
            source=Source.MANUAL,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            transaction_type=TransactionType.TRADE,
            side=Side.BUY,
            asset="BTC",
            quantity=Decimal("0.01"),
            confidence=1.0,
        )
        assert tx.asset == "BTC"


class TestWithdrawalAccountingAlignment:
    def test_withdrawal_creates_disposal_event(self):
        from backend.accounting.engine import AccountingEngine
        from backend.accounting.configuration import AccountingConfiguration
        from backend.models.transaction import CanonicalTransaction, TransactionType, Source
        from datetime import datetime, timezone
        from decimal import Decimal

        engine = AccountingEngine(AccountingConfiguration())
        tx = CanonicalTransaction(
            transaction_id="withdraw-1",
            source=Source.BINANCE,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            transaction_type=TransactionType.WITHDRAWAL,
            asset="BTC",
            quantity=Decimal("0.5"),
            confidence=1.0,
        )
        result = engine.process([tx])
        disposal_events = [e for e in result.events if e.event_type.value == "DISPOSAL"]
        assert len(disposal_events) == 1
        assert disposal_events[0].asset == "BTC"
        assert disposal_events[0].quantity == Decimal("0.5")

    def test_withdrawal_no_proceeds_warning(self):
        from backend.accounting.engine import AccountingEngine
        from backend.accounting.configuration import AccountingConfiguration
        from backend.models.transaction import CanonicalTransaction, TransactionType, Source
        from datetime import datetime, timezone
        from decimal import Decimal

        engine = AccountingEngine(AccountingConfiguration())
        tx = CanonicalTransaction(
            transaction_id="withdraw-2",
            source=Source.BINANCE,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            transaction_type=TransactionType.WITHDRAWAL,
            asset="BTC",
            quantity=Decimal("0.5"),
            confidence=1.0,
        )
        result = engine.process([tx])
        warning_codes = [w.code for w in result.warnings]
        assert "WITHDRAWAL_NO_PROCEEDS" in warning_codes

    def test_withdrawal_with_value_uses_as_proceeds(self):
        from backend.accounting.engine import AccountingEngine
        from backend.accounting.configuration import AccountingConfiguration
        from backend.models.transaction import CanonicalTransaction, TransactionType, Source
        from datetime import datetime, timezone
        from decimal import Decimal

        engine = AccountingEngine(AccountingConfiguration())
        tx = CanonicalTransaction(
            transaction_id="withdraw-3",
            source=Source.BINANCE,
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            transaction_type=TransactionType.WITHDRAWAL,
            asset="BTC",
            quantity=Decimal("0.5"),
            value=Decimal("15000"),
            quote_asset="USD",
            confidence=1.0,
        )
        result = engine.process([tx])
        disposal_events = [e for e in result.events if e.event_type.value == "DISPOSAL"]
        assert len(disposal_events) == 1
        assert disposal_events[0].proceeds == Decimal("15000")
        assert disposal_events[0].proceeds_currency == "USD"


class TestProcessEndpointHardening:
    def test_process_missing_content_type_rejected(self):
        csv_content = "Date(UTC),Pair,Type\n2024-01-01,BTC/USDT,Buy\n"
        files = {"file": ("test.csv", io.BytesIO(csv_content.encode("utf-8")), "")}
        response = client.post("/api/v1/process?timezone=UTC", files=files)
        assert response.status_code == 400

    def test_process_path_traversal_rejected(self):
        csv_content = "Date(UTC),Pair,Type\n2024-01-01,BTC/USDT,Buy\n"
        files = {"file": ("../test.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
        response = client.post("/api/v1/process?timezone=UTC", files=files)
        assert response.status_code == 400
        assert "Invalid filename" in response.json()["detail"]


class TestAccountEndpointHardening:
    def test_account_missing_content_type_rejected(self):
        csv_content = "Date(UTC),Pair,Type\n2024-01-01,BTC/USDT,Buy\n"
        files = {"file": ("test.csv", io.BytesIO(csv_content.encode("utf-8")), "")}
        response = client.post("/api/v1/account?timezone=UTC", files=files)
        assert response.status_code == 400

    def test_account_path_traversal_rejected(self):
        csv_content = "Date(UTC),Pair,Type\n2024-01-01,BTC/USDT,Buy\n"
        files = {"file": ("../test.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
        response = client.post("/api/v1/account?timezone=UTC", files=files)
        assert response.status_code == 400
        assert "Invalid filename" in response.json()["detail"]
