from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel

from backend.models.transaction import CanonicalTransaction, TransactionType


class TransferClassification(str, Enum):
    INTERNAL_TRANSFER = "INTERNAL_TRANSFER"


class TransferLeg(BaseModel):
    transaction_id: str
    source: str
    asset: str
    quantity: Decimal
    signed_amount: Decimal
    account: Optional[str]
    operation: Optional[str]
    timestamp: datetime
    transaction_type: TransactionType
    tx_hash: Optional[str] = None


class TransferMatch(BaseModel):
    transfer_id: str
    classification: TransferClassification
    source_transaction_id: str
    destination_transaction_id: str
    source_account: Optional[str]
    destination_account: Optional[str]
    asset: str
    quantity: Decimal
    timestamp: datetime
    confidence: int
    reasons: List[str]


class TransferResult(BaseModel):
    matches: List[TransferMatch]
    unmatched_leg_ids: List[str]


class TransferRules(ABC):
    @abstractmethod
    def extract_leg(self, tx: CanonicalTransaction) -> Optional[TransferLeg]:
        ...

    @abstractmethod
    def accounts_compatible(self, a: TransferLeg, b: TransferLeg) -> bool:
        ...


def _make_transfer_id(leg_a_id: str, leg_b_id: str) -> str:
    raw = "|".join(sorted([leg_a_id, leg_b_id]))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class TransferReconciler:
    def __init__(
        self,
        timestamp_tolerance_seconds: int = 1,
        rules: Optional[TransferRules] = None,
    ):
        if timestamp_tolerance_seconds < 0:
            raise ValueError("Timestamp tolerance must be non-negative.")
        self.tolerance_seconds = timestamp_tolerance_seconds
        # Default to the Binance rule layer; swappable for future sources.
        # Imported lazily to avoid a circular import between modules.
        if rules is None:
            from backend.reconciliation.binance_transfers import BinanceTransferRules

            rules = BinanceTransferRules()
        self.rules: TransferRules = rules

    def _timestamps_within(self, a: datetime, b: datetime) -> bool:
        if a is None or b is None:
            return False
        return abs((a - b).total_seconds()) <= self.tolerance_seconds

    def _is_match(self, a: TransferLeg, b: TransferLeg) -> bool:
        if (
            a.transaction_type != TransactionType.TRANSFER
            or b.transaction_type != TransactionType.TRANSFER
        ):
            return False
        if a.asset != b.asset:
            return False
        if a.quantity != b.quantity:
            return False
        if not (
            a.signed_amount < 0 < b.signed_amount
            or b.signed_amount < 0 < a.signed_amount
        ):
            return False
        if a.source == b.source:
            if not self._timestamps_within(a.timestamp, b.timestamp):
                return False
            if not self.rules.accounts_compatible(a, b):
                return False
            return True
        if a.tx_hash and b.tx_hash and a.tx_hash == b.tx_hash:
            if not self._timestamps_within(a.timestamp, b.timestamp):
                return False
            return True
        return False

    def _build_match(self, a: TransferLeg, b: TransferLeg) -> TransferMatch:
        if a.signed_amount < 0:
            src, dst = a, b
        else:
            src, dst = b, a
        delta = abs((a.timestamp - b.timestamp).total_seconds())
        confidence = 100 if delta == 0 else 95
        return TransferMatch(
            transfer_id=_make_transfer_id(a.transaction_id, b.transaction_id),
            classification=TransferClassification.INTERNAL_TRANSFER,
            source_transaction_id=src.transaction_id,
            destination_transaction_id=dst.transaction_id,
            source_account=src.account,
            destination_account=dst.account,
            asset=src.asset,
            quantity=src.quantity,
            timestamp=src.timestamp,
            confidence=confidence,
            reasons=[
                "same asset",
                "equal absolute quantity",
                "opposite source change signs",
                "compatible internal accounts",
                f"timestamp difference {int(round(delta))} seconds",
            ],
        )

    def reconcile(
        self, transactions: List[CanonicalTransaction]
    ) -> TransferResult:
        legs: List[TransferLeg] = []
        for tx in transactions:
            leg = self.rules.extract_leg(tx)
            if leg is not None:
                legs.append(leg)

        # Index by (asset, absolute quantity) to avoid O(n^2) across all legs.
        buckets: Dict[Tuple[str, str], List[TransferLeg]] = defaultdict(list)
        for leg in legs:
            buckets[(leg.asset, str(leg.quantity))].append(leg)

        matches: List[TransferMatch] = []
        used: set = set()

        for group in buckets.values():
            by_source: Dict[str, List[TransferLeg]] = defaultdict(list)
            for leg in group:
                by_source[leg.source].append(leg)

            for src_group in by_source.values():
                n = len(src_group)
                for i in range(n):
                    for j in range(i + 1, n):
                        a = src_group[i]
                        b = src_group[j]
                        if a.transaction_id in used or b.transaction_id in used:
                            continue
                        if self._is_match(a, b):
                            matches.append(self._build_match(a, b))
                            used.add(a.transaction_id)
                            used.add(b.transaction_id)

        for group in buckets.values():
            n = len(group)
            for i in range(n):
                for j in range(i + 1, n):
                    a = group[i]
                    b = group[j]
                    if a.transaction_id in used or b.transaction_id in used:
                        continue
                    if a.source == b.source:
                        continue
                    if a.tx_hash and b.tx_hash and a.tx_hash == b.tx_hash:
                        if self._timestamps_within(a.timestamp, b.timestamp):
                            matches.append(self._build_match(a, b))
                            used.add(a.transaction_id)
                            used.add(b.transaction_id)

        unmatched = [leg.transaction_id for leg in legs if leg.transaction_id not in used]
        return TransferResult(matches=matches, unmatched_leg_ids=unmatched)
