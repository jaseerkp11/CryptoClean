from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from backend.accounting.models import (
    AccountingEvent,
    AccountingEventType,
    AcquisitionLot,
    AcquisitionType,
    LotConsumption,
    WarningCode,
)
from backend.accounting.exceptions import make_warning
from backend.accounting.methods import FIFOMethod, ConsumptionPlan
from backend.models.transaction import CanonicalTransaction


class SwapHandler:
    def __init__(self):
        self._method = FIFOMethod()

    def process_swaps(
        self,
        transactions: List[CanonicalTransaction],
        convert_result: Optional[Any],
        lot_pool: Dict[str, Decimal],
        events: List[AccountingEvent],
        consumptions: List[LotConsumption],
        lots: List[AcquisitionLot],
        warnings_list: List,
        errors_list: List,
    ) -> None:
        swap_pairs, unpaired = self._group_swap_pairs(transactions, convert_result)

        for input_tx, output_tx in swap_pairs:
            self._process_swap_pair(
                input_tx, output_tx, lot_pool, events, consumptions, lots, warnings_list, errors_list
            )

        for tx in unpaired:
            events.append(
                AccountingEvent(
                    event_id=_make_event_id(tx.transaction_id, AccountingEventType.NON_ACCOUNTING.value),
                    event_type=AccountingEventType.NON_ACCOUNTING,
                    source_transaction_ids=[tx.transaction_id],
                    timestamp=tx.timestamp,
                    asset=tx.asset,
                    quantity=tx.quantity or Decimal("0"),
                    metadata={"reason": "swap accounting deferred; unmatched swap leg"},
                )
            )
            warnings_list.append(
                make_warning(
                    code=WarningCode.PARTIAL_SWAP_VALUATION,
                    message=f"Swap {tx.transaction_id} for {tx.asset} is deferred; no matching swap leg found.",
                    source_transaction_id=tx.transaction_id,
                )
            )

    def _group_swap_pairs(
        self,
        transactions: List[CanonicalTransaction],
        convert_result: Optional[Any],
    ) -> Tuple[List[Tuple[CanonicalTransaction, CanonicalTransaction]], List[CanonicalTransaction]]:
        pairs: List[Tuple[CanonicalTransaction, CanonicalTransaction]] = []
        used_ids = set()
        unpaired: List[CanonicalTransaction] = []

        convert_links: Dict[str, str] = {}
        if convert_result is not None:
            for finding in getattr(convert_result, "matches", []):
                input_id = getattr(finding, "input_transaction_id", None)
                output_id = getattr(finding, "output_transaction_id", None)
                if input_id and output_id:
                    convert_links[input_id] = output_id
                    convert_links[output_id] = input_id

        tx_map = {tx.transaction_id: tx for tx in transactions}

        for tx_id, linked_id in convert_links.items():
            if tx_id in used_ids or linked_id in used_ids:
                continue
            if tx_id in tx_map and linked_id in tx_map:
                input_tx = tx_map[tx_id]
                output_tx = tx_map[linked_id]
                pairs.append((input_tx, output_tx))
                used_ids.add(tx_id)
                used_ids.add(linked_id)

        swap_txs = [tx for tx in transactions if tx.transaction_type.value == "SWAP" and tx.transaction_id not in used_ids]
        swap_groups = _group_by_timestamp(swap_txs, tolerance_seconds=1)

        for group in swap_groups:
            sorted_group = sorted(group, key=lambda tx: tx.asset)
            for i in range(0, len(sorted_group) - 1, 2):
                input_tx = sorted_group[i]
                output_tx = sorted_group[i + 1]
                pairs.append((input_tx, output_tx))
                used_ids.add(input_tx.transaction_id)
                used_ids.add(output_tx.transaction_id)
            if len(sorted_group) % 2 != 0:
                last_tx = sorted_group[-1]
                if last_tx.transaction_id not in used_ids:
                    unpaired.append(last_tx)

        return pairs, unpaired

    def _process_swap_pair(
        self,
        input_tx: CanonicalTransaction,
        output_tx: CanonicalTransaction,
        lot_pool: Dict[str, Decimal],
        events: List[AccountingEvent],
        consumptions: List[LotConsumption],
        lots: List[AcquisitionLot],
        warnings_list: List,
        errors_list: List,
    ) -> None:
        disposal_proceeds, proceeds_currency, proceed_warnings = _resolve_proceeds(input_tx)
        for w in proceed_warnings:
            warnings_list.append(w)

        acquisition_cost, cost_currency, cost_warnings = _resolve_cost_basis(output_tx)
        for w in cost_warnings:
            warnings_list.append(w)

        if acquisition_cost is None and disposal_proceeds is not None:
            acquisition_cost = disposal_proceeds
            cost_currency = proceeds_currency
            if output_tx.fee is not None and output_tx.fee != 0:
                fee_asset = output_tx.fee_asset
                quote_asset = output_tx.quote_asset
                if fee_asset == quote_asset:
                    acquisition_cost = acquisition_cost - output_tx.fee
                elif fee_asset == output_tx.asset:
                    if output_tx.quantity is not None and output_tx.quantity > output_tx.fee:
                        pass
                    else:
                        warnings_list.append(
                            make_warning(
                                code=WarningCode.THIRD_ASSET_FEE,
                                message=f"Swap output base-asset fee {output_tx.fee} exceeds quantity {output_tx.quantity} for {output_tx.asset}. Acquisition cost basis preserved from disposal proceeds.",
                                source_transaction_id=output_tx.transaction_id,
                            )
                        )
                else:
                    pass

        disposal_event = AccountingEvent(
            event_id=_make_event_id(input_tx.transaction_id, AccountingEventType.DISPOSAL.value),
            event_type=AccountingEventType.DISPOSAL,
            source_transaction_ids=[input_tx.transaction_id],
            timestamp=input_tx.timestamp,
            asset=input_tx.asset,
            quantity=input_tx.quantity,
            proceeds=disposal_proceeds,
            proceeds_currency=proceeds_currency,
            fee=input_tx.fee,
            fee_asset=input_tx.fee_asset,
            linked_event_ids=[_make_event_id(output_tx.transaction_id, AccountingEventType.ACQUISITION.value)],
            metadata={"swap_input": True},
        )
        events.append(disposal_event)

        plan = self._method.select_lots(
            available_lots=lots,
            lot_remaining=lot_pool,
            disposal_quantity=input_tx.quantity,
            disposal_timestamp=input_tx.timestamp,
            disposal_transaction_id=input_tx.transaction_id,
            asset=input_tx.asset,
            cost_currency=proceeds_currency,
            disposal_proceeds=disposal_proceeds,
            proceeds_currency=proceeds_currency,
        )
        for err in plan.errors:
            errors_list.append(err)
        for w in plan.warnings:
            warnings_list.append(w)

        for consumption in plan.consumptions:
            consumptions.append(consumption)
            disposal_event.linked_lot_ids.append(consumption.lot_id)

        if plan.consumptions and all(c.unit_cost is not None for c in plan.consumptions):
            total_cost_allocated = sum(c.cost_allocated for c in plan.consumptions if c.cost_allocated is not None)
            total_realized_pnl = sum(c.realized_pnl for c in plan.consumptions if c.realized_pnl is not None)
            cost_currency = None
            pnl_currency = None
            for c in plan.consumptions:
                if c.cost_currency is not None:
                    cost_currency = c.cost_currency
                if c.pnl_currency is not None:
                    pnl_currency = c.pnl_currency
            replacement = AccountingEvent(
                event_id=disposal_event.event_id,
                event_type=disposal_event.event_type,
                source_transaction_ids=disposal_event.source_transaction_ids,
                timestamp=disposal_event.timestamp,
                asset=disposal_event.asset,
                quantity=disposal_event.quantity,
                cost_basis=total_cost_allocated if total_cost_allocated > 0 else None,
                cost_currency=cost_currency,
                proceeds=disposal_event.proceeds,
                proceeds_currency=disposal_event.proceeds_currency,
                realized_pnl=total_realized_pnl if total_realized_pnl != 0 else None,
                pnl_currency=pnl_currency,
                fee=disposal_event.fee,
                fee_asset=disposal_event.fee_asset,
                linked_lot_ids=disposal_event.linked_lot_ids,
                linked_event_ids=disposal_event.linked_event_ids,
                warnings=disposal_event.warnings,
                metadata=disposal_event.metadata,
            )
            events[-1] = replacement

        if plan.remaining_quantity > 0:
            warnings_list.append(
                make_warning(
                    code=WarningCode.INSUFFICIENT_LOTS,
                    message=f"Swap disposal quantity {input_tx.quantity} exceeds available lots for {input_tx.asset}. Shortage: {plan.shortage}",
                    source_transaction_id=input_tx.transaction_id,
                    context={"shortage": str(plan.shortage)},
                )
            )

        acquisition_event = AccountingEvent(
            event_id=_make_event_id(output_tx.transaction_id, AccountingEventType.ACQUISITION.value),
            event_type=AccountingEventType.ACQUISITION,
            source_transaction_ids=[output_tx.transaction_id],
            timestamp=output_tx.timestamp,
            asset=output_tx.asset,
            quantity=output_tx.quantity,
            cost_basis=acquisition_cost,
            cost_currency=cost_currency,
            fee=output_tx.fee,
            fee_asset=output_tx.fee_asset,
            linked_event_ids=[disposal_event.event_id],
            metadata={"swap_output": True},
        )
        events.append(acquisition_event)

        unit_cost: Optional[Decimal] = None
        total_cost: Optional[Decimal] = None
        if acquisition_cost is not None and output_tx.quantity is not None and output_tx.quantity > 0:
            unit_cost = acquisition_cost / output_tx.quantity
            total_cost = acquisition_cost

        lot = AcquisitionLot(
            lot_id=_make_lot_id(output_tx.transaction_id, output_tx.asset, output_tx.quantity, output_tx.timestamp),
            asset=output_tx.asset,
            acquired_quantity=output_tx.quantity,
            remaining_quantity=output_tx.quantity,
            unit_cost=unit_cost,
            total_cost=total_cost,
            cost_currency=cost_currency,
            acquired_timestamp=output_tx.timestamp,
            source_transaction_id=output_tx.transaction_id,
            acquisition_type=AcquisitionType.SWAP_IN,
            fee=output_tx.fee,
            fee_asset=output_tx.fee_asset,
            linked_event_id=acquisition_event.event_id,
        )
        lots.append(lot)
        lot_pool[lot.lot_id] = output_tx.quantity


def _group_by_timestamp(transactions: List[CanonicalTransaction], tolerance_seconds: int = 1) -> List[List[CanonicalTransaction]]:
    if not transactions:
        return []

    sorted_txs = sorted(transactions, key=lambda tx: tx.timestamp)
    groups: List[List[CanonicalTransaction]] = []
    current_group: List[CanonicalTransaction] = [sorted_txs[0]]

    for tx in sorted_txs[1:]:
        last = current_group[-1]
        if abs((tx.timestamp - last.timestamp).total_seconds()) <= tolerance_seconds:
            current_group.append(tx)
        else:
            groups.append(current_group)
            current_group = [tx]
    groups.append(current_group)
    return groups


def _resolve_cost_basis(tx: CanonicalTransaction) -> Tuple[Optional[Decimal], Optional[str], List]:
    import warnings as _warnings
    warnings = []
    cost_basis: Optional[Decimal] = None
    cost_currency: Optional[str] = getattr(tx, "quote_asset", None)

    if getattr(tx, "value", None) is not None:
        cost_basis = tx.value
    elif getattr(tx, "price", None) is not None and getattr(tx, "quantity", None) is not None:
        cost_basis = tx.price * tx.quantity
        cost_currency = getattr(tx, "quote_asset", None)
    else:
        warnings.append(
            make_warning(
                code=WarningCode.MISSING_COST_BASIS,
                message=f"Transaction {tx.transaction_id} for {tx.asset} has no price or value; cost basis is unknown.",
                source_transaction_id=tx.transaction_id,
            )
        )

    return cost_basis, cost_currency, warnings


def _resolve_proceeds(tx: CanonicalTransaction) -> Tuple[Optional[Decimal], Optional[str], List]:
    warnings = []
    proceeds: Optional[Decimal] = None
    proceeds_currency: Optional[str] = getattr(tx, "quote_asset", None)

    if getattr(tx, "value", None) is not None:
        proceeds = tx.value
    elif getattr(tx, "price", None) is not None and getattr(tx, "quantity", None) is not None:
        proceeds = tx.price * tx.quantity
        proceeds_currency = getattr(tx, "quote_asset", None)
    else:
        warnings.append(
            make_warning(
                code=WarningCode.MISSING_PROCEEDS,
                message=f"Transaction {tx.transaction_id} for {tx.asset} has no price or value; proceeds are unknown.",
                source_transaction_id=tx.transaction_id,
            )
        )

    return proceeds, proceeds_currency, warnings


def _make_event_id(tx_id: str, event_type: str) -> str:
    import hashlib

    raw = "|".join(sorted([tx_id, event_type]))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _make_lot_id(tx_id: str, asset: str, quantity: Decimal, timestamp) -> str:
    import hashlib

    raw = "|".join(sorted([tx_id, asset, str(quantity), str(timestamp)]))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
