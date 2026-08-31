from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel

from backend.models.transaction import CanonicalTransaction, TransactionType


class ConvertClassification(str, Enum):
    CONVERT = "CONVERT"


class ConvertLeg(BaseModel):
    transaction_id: str
    source: str
    account: str
    asset: str
    quantity: Decimal
    signed_amount: Decimal
    timestamp: datetime
    operation: str


class ConvertFinding(BaseModel):
    convert_id: str
    source: str
    timestamp: datetime
    input_transaction_id: str
    output_transaction_id: str
    input_asset: str
    input_quantity: Decimal
    output_asset: str
    output_quantity: Decimal
    account: str
    confidence: int
    reasons: List[str]
    warnings: List[str]


class ConvertResult(BaseModel):
    matches: List[ConvertFinding]
    unresolved_leg_ids: List[str]
    warnings: List[str]


class ConvertRules(ABC):
    @abstractmethod
    def extract_leg(self, tx: CanonicalTransaction) -> Optional[ConvertLeg]:
        ...


def _make_convert_id(leg_a_id: str, leg_b_id: str) -> str:
    raw = "|".join(sorted([leg_a_id, leg_b_id]))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class ConvertReconciler:
    def __init__(self, timestamp_tolerance_seconds: int = 1, rules: Optional[ConvertRules] = None):
        if timestamp_tolerance_seconds < 0:
            raise ValueError("Timestamp tolerance must be non-negative.")
        self.tolerance_seconds = timestamp_tolerance_seconds
        if rules is None:
            from backend.reconciliation.binance_converts import BinanceConvertRules

            rules = BinanceConvertRules()
        self.rules: ConvertRules = rules

    def _timestamps_within(self, a: datetime, b: datetime) -> bool:
        if a is None or b is None:
            return False
        return abs((a - b).total_seconds()) <= self.tolerance_seconds

    def reconcile(self, transactions: List[CanonicalTransaction]) -> ConvertResult:
        legs: List[ConvertLeg] = []
        for tx in transactions:
            leg = self.rules.extract_leg(tx)
            if leg is not None:
                legs.append(leg)

        buckets: Dict[Tuple[str, str], List[ConvertLeg]] = defaultdict(list)
        for leg in legs:
            buckets[(leg.source, leg.account)].append(leg)

        matches: List[ConvertFinding] = []
        used: set = set()
        warnings: List[str] = []

        for (source, account), group in buckets.items():
            negatives = [leg for leg in group if leg.signed_amount < 0]
            positives = [leg for leg in group if leg.signed_amount > 0]

            if len(negatives) == 1 and len(positives) == 1:
                neg = negatives[0]
                pos = positives[0]
                if neg.asset == pos.asset:
                    warnings.append(
                        f"same asset ({neg.asset}) on both sides of potential convert in {source}/{account}"
                    )
                    continue
                delta = abs((neg.timestamp - pos.timestamp).total_seconds())
                if delta <= self.tolerance_seconds:
                    confidence = 100 if delta == 0 else 95
                    input_leg, output_leg = neg, pos
                    convert_id = _make_convert_id(
                        input_leg.transaction_id, output_leg.transaction_id
                    )
                    finding = ConvertFinding(
                        convert_id=convert_id,
                        source=input_leg.source,
                        timestamp=input_leg.timestamp,
                        input_transaction_id=input_leg.transaction_id,
                        output_transaction_id=output_leg.transaction_id,
                        input_asset=input_leg.asset,
                        input_quantity=input_leg.quantity,
                        output_asset=output_leg.asset,
                        output_quantity=output_leg.quantity,
                        account=input_leg.account,
                        confidence=confidence,
                        reasons=[
                            "same source",
                            "same account",
                            "same operation: Binance Convert",
                            "opposite signed changes",
                            "different assets",
                            f"timestamp difference {int(round(delta))} seconds",
                        ],
                        warnings=[],
                    )
                    matches.append(finding)
                    used.add(input_leg.transaction_id)
                    used.add(output_leg.transaction_id)
                else:
                    warnings.append(
                        f"timestamp outside tolerance for potential convert pair in {source}/{account}"
                    )
            else:
                warnings.append(
                    f"ambiguous convert candidates in {source}/{account}: "
                    f"{len(negatives)} negative, {len(positives)} positive legs"
                )

        unresolved = [leg.transaction_id for leg in legs if leg.transaction_id not in used]
        return ConvertResult(matches=matches, unresolved_leg_ids=unresolved, warnings=warnings)


ConvertLeg.model_rebuild()
ConvertFinding.model_rebuild()
ConvertResult.model_rebuild()
