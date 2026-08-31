from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from backend.models.transaction import CanonicalTransaction, Source


class CommentFinding(BaseModel):
    transaction_id: str
    source: str
    raw_remark: str
    preserved: bool = True


class CommentResult(BaseModel):
    comments: List[CommentFinding] = []


class BinanceCommentRules:
    PRESERVE_RAW_REMARK = True
    STRIP_USER_ID = True
    EXTRACT_IDENTIFIERS = True

    @classmethod
    def preserve_remark(cls, remark: Optional[str]) -> Optional[str]:
        if remark is None:
            return None
        return remark

    @classmethod
    def is_user_id_remark(cls, remark: Optional[str]) -> bool:
        if not remark:
            return False
        return remark.strip().upper() in {"REDACTED", "USER ID", "USERID"}


class CommentEngine:
    def __init__(self, preserve_raw_remarks: bool = True):
        self.preserve_raw_remarks = preserve_raw_remarks

    def process(self, transactions: List[CanonicalTransaction]) -> CommentResult:
        comments: List[CommentFinding] = []
        for tx in transactions:
            if not tx.metadata:
                continue
            raw_remark = tx.metadata.get("source_remark")
            if raw_remark is None:
                continue
            if isinstance(raw_remark, str) and not raw_remark.strip():
                continue

            if tx.source == Source.BINANCE:
                if BinanceCommentRules.is_user_id_remark(raw_remark):
                    continue
                preserved_remark = BinanceCommentRules.preserve_remark(raw_remark)
            else:
                preserved_remark = raw_remark if self.preserve_raw_remarks else raw_remark.strip()

            comments.append(
                CommentFinding(
                    transaction_id=tx.transaction_id,
                    source=tx.source.value,
                    raw_remark=preserved_remark,
                    preserved=True,
                )
            )
        return CommentResult(comments=comments)
