import pytest

from backend.models.transaction import CanonicalTransaction, Source, TransactionType
from backend.processing.comments import BinanceCommentRules, CommentEngine, CommentFinding, CommentResult


BINANCE_TIMESTAMP = "2024-10-20T21:01:19+00:00"


def _binance_tx(remark: str = "") -> CanonicalTransaction:
    return CanonicalTransaction(
        transaction_id="tx1",
        source=Source.BINANCE,
        source_transaction_id=None,
        timestamp=BINANCE_TIMESTAMP,
        transaction_type=TransactionType.DEPOSIT,
        asset="SOL",
        quantity=1.0,
        confidence=1.0,
        metadata={"source_remark": remark},
    )


def test_binance_raw_remark_preserved_unchanged():
    remark = "P2P - abc123 TradeID - 456 extra details"
    engine = CommentEngine()
    result = engine.process([_binance_tx(remark)])
    assert len(result.comments) == 1
    assert result.comments[0].raw_remark == remark
    assert result.comments[0].preserved is True


def test_binance_empty_remark_skipped():
    engine = CommentEngine()
    result = engine.process([_binance_tx("")])
    assert len(result.comments) == 0


def test_binance_none_remark_skipped():
    engine = CommentEngine()
    tx = CanonicalTransaction(
        transaction_id="tx1",
        source=Source.BINANCE,
        source_transaction_id=None,
        timestamp=BINANCE_TIMESTAMP,
        transaction_type=TransactionType.DEPOSIT,
        asset="SOL",
        quantity=1.0,
        confidence=1.0,
        metadata={},
    )
    result = engine.process([tx])
    assert len(result.comments) == 0


def test_binance_user_id_remark_excluded():
    engine = CommentEngine()
    result = engine.process([_binance_tx("REDACTED")])
    assert len(result.comments) == 0


def test_binance_user_id_case_insensitive_excluded():
    engine = CommentEngine()
    result = engine.process([_binance_tx("redacted")])
    assert len(result.comments) == 0


def test_generic_non_binance_remark_preserved():
    tx = CanonicalTransaction(
        transaction_id="tx2",
        source=Source.COINBASE,
        source_transaction_id=None,
        timestamp=BINANCE_TIMESTAMP,
        transaction_type=TransactionType.DEPOSIT,
        asset="BTC",
        quantity=0.01,
        confidence=1.0,
        metadata={"source_remark": "some note"},
    )
    engine = CommentEngine()
    result = engine.process([tx])
    assert len(result.comments) == 1
    assert result.comments[0].raw_remark == "some note"


def test_user_id_never_in_comment_output():
    engine = CommentEngine()
    txs = [
        _binance_tx("P2P - 12345"),
        CanonicalTransaction(
            transaction_id="tx3",
            source=Source.BINANCE,
            source_transaction_id=None,
            timestamp=BINANCE_TIMESTAMP,
            transaction_type=TransactionType.FEE,
            asset="USDT",
            quantity=0.1,
            confidence=1.0,
            metadata={"source_remark": "REDACTED", "user_id": "999"},
        ),
    ]
    result = engine.process(txs)
    output = str(result.model_dump())
    assert "REDACTED" not in output
    assert "999" not in output
    assert "user_id" not in output


def test_comment_engine_isolated_from_other_categories():
    remark = "P2P - abc123"
    tx = _binance_tx(remark)
    engine = CommentEngine()
    result = engine.process([tx])
    assert result.comments[0].transaction_id == "tx1"
    assert result.comments[0].source == "binance"
    assert result.comments[0].raw_remark == remark
    assert len(result.comments) == 1


def test_binance_comment_rules_preserve_remark():
    remark = "TradeID - 789"
    preserved = BinanceCommentRules.preserve_remark(remark)
    assert preserved == remark


def test_binance_comment_rules_user_id_detection():
    assert BinanceCommentRules.is_user_id_remark("REDACTED") is True
    assert BinanceCommentRules.is_user_id_remark("redacted") is True
    assert BinanceCommentRules.is_user_id_remark("TradeID - 123") is False
    assert BinanceCommentRules.is_user_id_remark("") is False


def test_comment_result_empty_by_default():
    result = CommentResult()
    assert result.comments == []


def test_comment_finding_defaults():
    finding = CommentFinding(transaction_id="tx1", source="binance", raw_remark="test")
    assert finding.preserved is True


def test_multiple_binance_remarks():
    engine = CommentEngine()
    txs = [
        _binance_tx("P2P - 111"),
        _binance_tx("TradeID - 222"),
        _binance_tx("REDACTED"),
    ]
    result = engine.process(txs)
    assert len(result.comments) == 2
    assert result.comments[0].raw_remark == "P2P - 111"
    assert result.comments[1].raw_remark == "TradeID - 222"


def test_comment_count_in_summary():
    from backend.processing.models import ProcessingSummary
    from backend.processing.pipeline import ProcessingPipeline

    pipeline = ProcessingPipeline()
    csv_content = """User ID,Time,Account,Operation,Coin,Change,Remark
REDACTED,2024-10-20 21:01:19,Spot,Deposit,SOL,+0.0215519,note1
REDACTED,2024-10-20 21:01:19,Spot,Binance Convert,USDT,+3.42578053,
REDACTED,2024-10-20 21:01:19,Spot,Binance Convert,SOL,-0.0215519,note2
"""
    result = pipeline.process_csv_content(csv_content, "UTC")
    assert result.summary.comments == 2


def test_api_process_endpoint_includes_comments():
    import io
    from fastapi.testclient import TestClient
    from backend.main import app

    csv_content = """User ID,Time,Account,Operation,Coin,Change,Remark
REDACTED,2024-10-20 21:01:19,Spot,Deposit,SOL,+0.0215519,hello world
REDACTED,2024-10-20 21:01:19,Spot,Binance Convert,USDT,+3.42578053,
"""
    client = TestClient(app)
    files = {"file": ("binance_export.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/api/v1/process?timezone=UTC", files=files)
    assert response.status_code == 200
    data = response.json()
    assert "comment_findings" in data
    assert data["summary"]["comments"] == 1
