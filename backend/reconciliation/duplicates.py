from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Tuple

from pydantic import BaseModel

from backend.models.transaction import CanonicalTransaction, TransactionType


class DuplicateClassification(str, Enum):
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    PROBABLE_DUPLICATE = "PROBABLE_DUPLICATE"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
    UNIQUE = "UNIQUE"


class DuplicateCandidate(BaseModel):
    transaction_ids: List[str]
    classification: DuplicateClassification
    score: int
    reasons: List[str]


class DuplicateGroup(BaseModel):
    group_id: str
    classification: DuplicateClassification
    score: int
    transaction_ids: List[str]
    reasons: List[str]


class DuplicateResult(BaseModel):
    groups: List[DuplicateGroup]
    candidates: List[DuplicateCandidate]
    unique_transaction_ids: List[str]


# --- Scoring weights (deterministic, documented) ---
WEIGHT_SOURCE_TX_ID = 70  # very strong
WEIGHT_TX_HASH = 70       # very strong (blockchain identifier)
WEIGHT_SOURCE = 12
WEIGHT_TYPE = 12
WEIGHT_SIDE = 6
WEIGHT_ASSET = 16
WEIGHT_QUANTITY = 16
WEIGHT_TIMESTAMP = 16
WEIGHT_QUOTE_ASSET = 4
WEIGHT_VALUE = 4
WEIGHT_FEE = 4
WEIGHT_FEE_ASSET = 4
WEIGHT_WALLET = 6
WEIGHT_COUNTERPARTY = 6

# --- Thresholds ---
THRESHOLD_EXACT = 100
THRESHOLD_PROBABLE = 90
THRESHOLD_POSSIBLE = 70

# Transactions lacking a strong identifier require a timestamp within tolerance
# before they can be considered secondary duplicates.


class DuplicateDetector:
    def __init__(
        self,
        timestamp_tolerance_seconds: int = 1,
        max_fingerprint_bucket_size: int = 500,
    ):
        if timestamp_tolerance_seconds < 0:
            raise ValueError("Timestamp tolerance must be non-negative.")
        if max_fingerprint_bucket_size < 1:
            raise ValueError("max_fingerprint_bucket_size must be at least 1.")
        self.tolerance_seconds = timestamp_tolerance_seconds
        self.max_fingerprint_bucket_size = max_fingerprint_bucket_size

    @staticmethod
    def _classify(score: int) -> DuplicateClassification:
        if score >= THRESHOLD_EXACT:
            return DuplicateClassification.EXACT_DUPLICATE
        if score >= THRESHOLD_PROBABLE:
            return DuplicateClassification.PROBABLE_DUPLICATE
        if score >= THRESHOLD_POSSIBLE:
            return DuplicateClassification.POSSIBLE_DUPLICATE
        return DuplicateClassification.UNIQUE

    def _timestamps_within_tolerance(self, a: datetime, b: datetime) -> bool:
        if a is None or b is None:
            return False
        return abs((a - b).total_seconds()) <= self.tolerance_seconds

    def _score_pair(
        self, a: CanonicalTransaction, b: CanonicalTransaction
    ) -> Tuple[int, List[str]]:
        # Exact duplicate: same deterministic transaction id AND same source.
        # Cross-exchange transactions with same ID are not automatically duplicates.
        if a.transaction_id == b.transaction_id and a.source == b.source:
            return 100, ["identical transaction ID"]

        score = 0
        reasons: List[str] = []
        strong = False

        if (
            a.source == b.source
            and a.source_transaction_id
            and a.source_transaction_id == b.source_transaction_id
        ):
            score += WEIGHT_SOURCE_TX_ID
            strong = True
            reasons.append("same source transaction ID")

        if a.tx_hash and b.tx_hash and a.tx_hash == b.tx_hash:
            score += WEIGHT_TX_HASH
            strong = True
            reasons.append("same tx_hash")

        # Transfers without a strong identifier are treated conservatively:
        # two transfer legs are usually opposite sides of one movement.
        if (
            a.transaction_type == TransactionType.TRANSFER
            and b.transaction_type == TransactionType.TRANSFER
            and not strong
        ):
            return 0, [
                "transfer pairs require a strong identifier to be considered duplicates"
            ]

        if not strong:
            if not self._timestamps_within_tolerance(a.timestamp, b.timestamp):
                return 0, ["no strong identifier and timestamps outside tolerance"]

        if self._timestamps_within_tolerance(a.timestamp, b.timestamp):
            score += WEIGHT_TIMESTAMP
            reasons.append(f"timestamp within {self.tolerance_seconds} second(s)")

        if a.source == b.source:
            score += WEIGHT_SOURCE
            reasons.append("same source")
        if a.transaction_type == b.transaction_type:
            score += WEIGHT_TYPE
            reasons.append("same transaction type")
        if a.side == b.side:
            score += WEIGHT_SIDE
            reasons.append("same side")
        if a.asset == b.asset:
            score += WEIGHT_ASSET
            reasons.append("same asset")
        if (
            a.quantity is not None
            and b.quantity is not None
            and a.quantity == b.quantity
        ):
            score += WEIGHT_QUANTITY
            reasons.append("same quantity")
        if a.quote_asset and b.quote_asset and a.quote_asset == b.quote_asset:
            score += WEIGHT_QUOTE_ASSET
            reasons.append("same quote asset")
        if a.value is not None and b.value is not None and a.value == b.value:
            score += WEIGHT_VALUE
            reasons.append("same value")
        if a.fee is not None and b.fee is not None and a.fee == b.fee:
            score += WEIGHT_FEE
            reasons.append("same fee")
        if a.fee_asset and b.fee_asset and a.fee_asset == b.fee_asset:
            score += WEIGHT_FEE_ASSET
            reasons.append("same fee asset")
        if a.wallet and b.wallet and a.wallet == b.wallet:
            score += WEIGHT_WALLET
            reasons.append("same wallet")
        if a.counterparty and b.counterparty and a.counterparty == b.counterparty:
            score += WEIGHT_COUNTERPARTY
            reasons.append("same counterparty")

        # Never let a non-exact pair reach the exact-duplicate score.
        score = min(score, 99)
        return score, reasons

    def detect(
        self, transactions: List[CanonicalTransaction]
    ) -> DuplicateResult:
        n = len(transactions)
        id_bucket: Dict[str, List[int]] = defaultdict(list)
        stx_bucket: Dict[Tuple[str, Optional[str]], List[int]] = defaultdict(list)
        txhash_bucket: Dict[Optional[str], List[int]] = defaultdict(list)
        fp_bucket: Dict[Tuple, List[int]] = defaultdict(list)
        fp_time_bucket: Dict[Tuple, List[int]] = defaultdict(list)

        for idx, tx in enumerate(transactions):
            id_bucket[tx.transaction_id].append(idx)
            if tx.source_transaction_id:
                stx_bucket[(tx.source, tx.source_transaction_id)].append(idx)
            if tx.tx_hash:
                txhash_bucket[tx.tx_hash].append(idx)
            qty_key = str(tx.quantity) if tx.quantity is not None else ""
            fp_key = (tx.source, tx.asset, qty_key)
            fp_bucket[fp_key].append(idx)
            if self.tolerance_seconds > 0:
                window = int(
                    tx.timestamp.timestamp() // self.tolerance_seconds
                )
            else:
                window = 0
            fp_time_bucket[(fp_key, window)].append(idx)

        pair_scores: Dict[FrozenSet[int], Tuple[int, List[str]]] = {}

        def consider(i: int, j: int) -> None:
            if i == j:
                return
            key = frozenset((i, j))
            if key in pair_scores:
                return
            score, reasons = self._score_pair(transactions[i], transactions[j])
            pair_scores[key] = (score, reasons)

        for bucket in list(id_bucket.values()) + list(stx_bucket.values()) + list(
            txhash_bucket.values()
        ):
            for i in range(len(bucket)):
                for j in range(i + 1, len(bucket)):
                    consider(bucket[i], bucket[j])

        for fp_key, bucket in fp_bucket.items():
            if len(bucket) <= 1:
                continue
            if len(bucket) <= self.max_fingerprint_bucket_size:
                sorted_bucket = sorted(bucket, key=lambda i: transactions[i].timestamp)
                for i in range(len(sorted_bucket)):
                    for j in range(i + 1, len(sorted_bucket)):
                        if not self._timestamps_within_tolerance(
                            transactions[sorted_bucket[i]].timestamp,
                            transactions[sorted_bucket[j]].timestamp,
                        ):
                            break
                        consider(sorted_bucket[i], sorted_bucket[j])
            else:
                base_key = (fp_key[0], fp_key[1], fp_key[2])
                windows = sorted(
                    {
                        k[1]
                        for k in fp_time_bucket
                        if k[0] == base_key
                    }
                )
                for w in windows:
                    adjacent = [
                        idx
                        for k, idxs in fp_time_bucket.items()
                        if k[0] == base_key and k[1] in (w - 1, w, w + 1)
                        for idx in idxs
                    ]
                    if len(adjacent) <= 1:
                        continue
                    sorted_adj = sorted(
                        adjacent, key=lambda i: transactions[i].timestamp
                    )
                    for i in range(len(sorted_adj)):
                        for j in range(i + 1, len(sorted_adj)):
                            if not self._timestamps_within_tolerance(
                                transactions[sorted_adj[i]].timestamp,
                                transactions[sorted_adj[j]].timestamp,
                            ):
                                break
                            consider(sorted_adj[i], sorted_adj[j])

        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry

        for key, (score, _) in pair_scores.items():
            if score >= THRESHOLD_POSSIBLE:
                i, j = tuple(key)
                union(i, j)

        comp_best: Dict[int, Tuple[int, List[str]]] = {}
        for key, (score, reasons) in pair_scores.items():
            if score >= THRESHOLD_POSSIBLE:
                i, j = tuple(key)
                root = find(i)
                if root not in comp_best or score > comp_best[root][0]:
                    comp_best[root] = (score, reasons)

        groups: List[DuplicateGroup] = []
        grouped_ids: set = set()
        gid = 0
        for root, (best_score, best_reasons) in comp_best.items():
            members = [idx for idx in range(n) if find(idx) == root]
            classification = self._classify(best_score)
            tx_ids = [transactions[idx].transaction_id for idx in members]
            grouped_ids.update(tx_ids)
            groups.append(
                DuplicateGroup(
                    group_id=f"dup_{gid}",
                    classification=classification,
                    score=best_score,
                    transaction_ids=tx_ids,
                    reasons=best_reasons,
                )
            )
            gid += 1

        candidates: List[DuplicateCandidate] = []
        for key, (score, reasons) in pair_scores.items():
            if score >= THRESHOLD_POSSIBLE:
                i, j = tuple(key)
                candidates.append(
                    DuplicateCandidate(
                        transaction_ids=[
                            transactions[i].transaction_id,
                            transactions[j].transaction_id,
                        ],
                        classification=self._classify(score),
                        score=score,
                        reasons=reasons,
                    )
                )

        unique_ids = [
            tx.transaction_id
            for tx in transactions
            if tx.transaction_id not in grouped_ids
        ]
        for group in groups:
            for tx_id in group.transaction_ids:
                grouped_ids.discard(tx_id)
            unique_ids.append(group.transaction_ids[0])

        return DuplicateResult(
            groups=groups, candidates=candidates, unique_transaction_ids=unique_ids
        )
