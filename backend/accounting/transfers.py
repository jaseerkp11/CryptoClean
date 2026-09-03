from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from backend.accounting.models import (
    AccountingEvent,
    AccountingEventType,
    WarningCode,
)
from backend.accounting.exceptions import make_warning


def process_transfer(
    tx: Any,
    matched_transfer_ids: set,
    transfer_matches: Optional[Any],
    events: List[AccountingEvent],
    warnings_list: List,
    lot_pool: Optional[Dict[str, Decimal]] = None,
    all_lots: Optional[List[Any]] = None,
) -> None:
    is_matched = tx.transaction_id in matched_transfer_ids

    linked_transfer_id: Optional[str] = None
    if is_matched and transfer_matches is not None:
        for match in getattr(transfer_matches, "matches", []):
            leg_a = getattr(match, "source_transaction_id", None)
            leg_b = getattr(match, "destination_transaction_id", None)
            if tx.transaction_id == leg_a:
                linked_transfer_id = leg_b
                break
            if tx.transaction_id == leg_b:
                linked_transfer_id = leg_a
                break

    linked_lot_ids: List[str] = []
    if is_matched and lot_pool is not None and all_lots is not None and tx.quantity is not None:
        remaining = tx.quantity
        sorted_lots = sorted(
            [l for l in all_lots if l.asset == tx.asset],
            key=lambda l: (l.acquired_timestamp, l.lot_id),
        )
        for lot in sorted_lots:
            if remaining <= 0:
                break
            available = lot_pool.get(lot.lot_id, Decimal("0"))
            if available <= 0:
                continue
            linked_lot_ids.append(lot.lot_id)
            remaining -= available

    event = AccountingEvent(
        event_id=_make_event_id(tx.transaction_id, AccountingEventType.TRANSFER.value),
        event_type=AccountingEventType.TRANSFER,
        source_transaction_ids=[tx.transaction_id],
        timestamp=tx.timestamp,
        asset=tx.asset,
        quantity=tx.quantity or Decimal("0"),
        linked_event_ids=[linked_transfer_id] if linked_transfer_id else [],
        linked_lot_ids=linked_lot_ids,
        metadata={"matched": is_matched},
    )
    events.append(event)

    if not is_matched:
        warnings_list.append(
            make_warning(
                code=WarningCode.UNMATCHED_TRANSFER,
                message=f"Transfer {tx.transaction_id} is not matched by reconciliation.",
                source_transaction_id=tx.transaction_id,
            )
        )


def _make_event_id(tx_id: str, event_type: str) -> str:
    import hashlib

    raw = "|".join(sorted([tx_id, event_type]))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
