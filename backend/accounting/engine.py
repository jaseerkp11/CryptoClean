from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from backend.accounting.configuration import AccountingConfiguration, CostBasisMethodType
from backend.accounting.exceptions import (
    AccountingException,
    AccountingWarning,
    make_exception,
    make_warning,
    ExceptionCode,
    WarningCode,
)
from backend.accounting.fees import apply_acquisition_fee, apply_disposal_fee
from backend.accounting.methods import (
    FIFOMethod,
    CostBasisMethod,
    ConsumptionPlan,
)
from backend.accounting.models import (
    AccountingEvent,
    AccountingResult,
    AccountingSummary,
    AcquisitionLot,
    AcquisitionType,
    AccountingEventType,
    LotConsumption,
    RealizedPnL,
)
from backend.accounting.swaps import SwapHandler
from backend.accounting.transfers import process_transfer
from backend.models.transaction import CanonicalTransaction, Source, TransactionType


class InsufficientLotsError(Exception):
    pass


class AccountingEngine:
    def __init__(self, configuration: Optional[AccountingConfiguration] = None):
        self.configuration = configuration or AccountingConfiguration()
        self._method: CostBasisMethod = self._resolve_method()
        self._warnings: List[AccountingWarning] = []
        self._errors: List[AccountingException] = []

    def _resolve_method(self) -> CostBasisMethod:
        return FIFOMethod()

    def process(
        self,
        transactions: List[CanonicalTransaction],
        transfer_result: Optional[Any] = None,
        convert_result: Optional[Any] = None,
        comment_result: Optional[Any] = None,
        unique_transaction_ids: Optional[set] = None,
    ) -> AccountingResult:
        self._warnings = []
        self._errors = []

        events: List[AccountingEvent] = []
        lots: List[AcquisitionLot] = []
        consumptions: List[LotConsumption] = []

        matched_transfer_ids: set = set()
        transfer_matches = None
        if transfer_result is not None:
            transfer_matches = transfer_result
            for match in getattr(transfer_result, "matches", []):
                matched_transfer_ids.add(getattr(match, "source_transaction_id", None))
                matched_transfer_ids.add(getattr(match, "destination_transaction_id", None))

        lot_pool: Dict[str, Decimal] = {}
        swap_candidates: List[CanonicalTransaction] = []
        processed_tx_ids: set = set()

        for tx in transactions:
            if unique_transaction_ids is not None and tx.transaction_id not in unique_transaction_ids:
                continue
            if tx.transaction_id in processed_tx_ids:
                continue
            processed_tx_ids.add(tx.transaction_id)
            tx_type = tx.transaction_type
            side = tx.side

            if tx_type == TransactionType.TRADE and side == "BUY":
                self._process_acquisition(tx, AcquisitionType.BUY, lot_pool, events, lots)
            elif tx_type == TransactionType.TRADE and side == "SELL":
                self._process_disposal(tx, lot_pool, events, consumptions, lots)
            elif tx_type == TransactionType.DEPOSIT:
                self._process_deposit(tx, lot_pool, events, lots)
            elif tx_type == TransactionType.WITHDRAWAL:
                self._process_withdrawal(tx, lot_pool, events, consumptions, lots)
            elif tx_type == TransactionType.TRANSFER:
                process_transfer(tx, matched_transfer_ids, transfer_matches, events, self._warnings, lot_pool=lot_pool, all_lots=lots)
            elif tx_type == TransactionType.SWAP:
                swap_candidates.append(tx)
            elif tx_type == TransactionType.UNKNOWN:
                is_convert = False
                if convert_result is not None:
                    for finding in getattr(convert_result, "matches", []):
                        if tx.transaction_id in {finding.input_transaction_id, finding.output_transaction_id}:
                            is_convert = True
                            break
                if is_convert:
                    swap_candidates.append(tx)
                else:
                    self._process_unknown(tx, events)
            else:
                events.append(
                    AccountingEvent(
                        event_id=_make_event_id(tx.transaction_id, AccountingEventType.NON_ACCOUNTING.value),
                        event_type=AccountingEventType.NON_ACCOUNTING,
                        source_transaction_ids=[tx.transaction_id],
                        timestamp=tx.timestamp,
                        asset=tx.asset or "",
                        quantity=tx.quantity or Decimal("0"),
                        metadata={"reason": f"unhandled transaction type: {tx_type}"},
                    )
                )

        if swap_candidates:
            SwapHandler().process_swaps(
                swap_candidates,
                convert_result,
                lot_pool,
                events,
                consumptions,
                lots,
                self._warnings,
                self._errors,
            )

        final_lots = self._finalize_lots(lots, consumptions, lot_pool)
        realized_pnl = self._aggregate_realized_pnl(consumptions, events)

        summary = AccountingSummary(
            total_events=len(events),
            acquisition_events=sum(1 for e in events if e.event_type == AccountingEventType.ACQUISITION),
            disposal_events=sum(1 for e in events if e.event_type == AccountingEventType.DISPOSAL),
            transfer_events=sum(1 for e in events if e.event_type == AccountingEventType.TRANSFER),
            swap_events=sum(1 for e in events if e.event_type == AccountingEventType.SWAP),
            total_lots_created=len(final_lots),
            total_lots_consumed=len(consumptions),
            total_realized_pnl=realized_pnl[0].total_realized_pnl if realized_pnl else None,
            pnl_currency=realized_pnl[0].currency if realized_pnl else None,
            warnings_count=len(self._warnings),
            errors_count=len(self._errors),
        )

        return AccountingResult(
            events=events,
            lots=final_lots,
            consumptions=consumptions,
            realized_pnl=realized_pnl if realized_pnl else [],
            warnings=self._warnings,
            errors=self._errors,
            summary=summary,
        )

    def _finalize_lots(
        self,
        lots: List[AcquisitionLot],
        consumptions: List[LotConsumption],
        lot_pool: Dict[str, Decimal],
    ) -> List[AcquisitionLot]:
        consumed: Dict[str, Decimal] = {}
        for c in consumptions:
            consumed[c.lot_id] = consumed.get(c.lot_id, Decimal("0")) + c.quantity_consumed
        final = []
        for lot in lots:
            consumed_qty = consumed.get(lot.lot_id, Decimal("0"))
            remaining = lot.acquired_quantity - consumed_qty
            if remaining < 0:
                self._warnings.append(
                    make_warning(
                        code=WarningCode.INSUFFICIENT_LOTS,
                        message=f"Lot {lot.lot_id} for {lot.asset} has negative remaining quantity {remaining}; clamped to 0.",
                        source_transaction_id=lot.source_transaction_id,
                        context={"lot_id": lot.lot_id, "consumed": str(consumed_qty), "acquired": str(lot.acquired_quantity)},
                    )
                )
                remaining = Decimal("0")
            final.append(
                AcquisitionLot(
                    lot_id=lot.lot_id,
                    asset=lot.asset,
                    acquired_quantity=lot.acquired_quantity,
                    remaining_quantity=remaining,
                    unit_cost=lot.unit_cost,
                    total_cost=lot.total_cost,
                    cost_currency=lot.cost_currency,
                    acquired_timestamp=lot.acquired_timestamp,
                    source_transaction_id=lot.source_transaction_id,
                    acquisition_type=lot.acquisition_type,
                    fee=lot.fee,
                    fee_asset=lot.fee_asset,
                    linked_event_id=lot.linked_event_id,
                )
            )
        return final

    def _aggregate_realized_pnl(
        self,
        consumptions: List[LotConsumption],
        events: List[AccountingEvent],
    ) -> List[RealizedPnL]:
        disposal_events = {tx_id: e for e in events if e.event_type == AccountingEventType.DISPOSAL for tx_id in e.source_transaction_ids}
        by_currency: Dict[str, List[LotConsumption]] = {}
        for c in consumptions:
            if c.realized_pnl is not None and c.disposal_event_id in disposal_events:
                currency = c.pnl_currency or c.proceeds_currency
                if currency is None:
                    continue
                by_currency.setdefault(currency, []).append(c)
        if not by_currency:
            return []
        aggregates: List[RealizedPnL] = []
        for currency, pnl_consumptions in by_currency.items():
            total = sum(c.realized_pnl for c in pnl_consumptions)
            pnl_ids: set = set()
            lot_ids: set = set()
            event_ids: set = set()
            timestamps = []
            for c in pnl_consumptions:
                pnl_ids.add(c.consumption_id)
                lot_ids.add(c.lot_id)
                event_ids.add(disposal_events[c.disposal_event_id].event_id)
                timestamps.append(c.consumed_timestamp)
            timestamps.sort()
            from_timestamp = timestamps[0]
            to_timestamp = timestamps[-1]
            pnl_id = _make_pnl_id(sorted(pnl_ids), currency, from_timestamp, to_timestamp)
            aggregates.append(
                RealizedPnL(
                    pnl_id=pnl_id,
                    asset="ALL",
                    total_realized_pnl=total,
                    currency=currency,
                    consumption_ids=sorted(pnl_ids),
                    lot_ids=sorted(lot_ids),
                    event_ids=sorted(event_ids),
                    from_timestamp=from_timestamp,
                    to_timestamp=to_timestamp,
                )
            )
        aggregates.sort(key=lambda pnl: (pnl.currency, pnl.from_timestamp))
        return aggregates

    def _process_acquisition(
        self,
        tx: CanonicalTransaction,
        acquisition_type: AcquisitionType,
        lot_pool: Dict[str, Decimal],
        events: List[AccountingEvent],
        lots: List[AcquisitionLot],
    ) -> None:
        cost_basis, cost_currency, warnings = _resolve_cost_basis(tx)
        for w in warnings:
            self._warnings.append(w)

        adjusted_cost_basis = cost_basis
        adjusted_quantity = tx.quantity
        original_quantity = tx.quantity
        if tx.fee is not None and tx.fee != 0:
            adjusted_cost_basis, adjusted_quantity, fee_warnings = apply_acquisition_fee(
                cost_basis=cost_basis,
                quantity=tx.quantity,
                fee=tx.fee,
                fee_asset=tx.fee_asset,
                asset=tx.asset,
                quote_asset=tx.quote_asset,
                source_transaction_id=tx.transaction_id,
            )
            for w in fee_warnings:
                self._warnings.append(w)

        unit_cost: Optional[Decimal] = None
        total_cost: Optional[Decimal] = None
        if adjusted_cost_basis is not None and original_quantity is not None and original_quantity > 0:
            unit_cost = adjusted_cost_basis / original_quantity
            total_cost = adjusted_cost_basis

        event = AccountingEvent(
            event_id=_make_event_id(tx.transaction_id, AccountingEventType.ACQUISITION.value),
            event_type=AccountingEventType.ACQUISITION,
            source_transaction_ids=[tx.transaction_id],
            timestamp=tx.timestamp,
            asset=tx.asset,
            quantity=adjusted_quantity,
            cost_basis=adjusted_cost_basis,
            cost_currency=cost_currency,
            fee=tx.fee,
            fee_asset=tx.fee_asset,
            metadata={"acquisition_type": acquisition_type.value},
        )
        events.append(event)

        lot = AcquisitionLot(
            lot_id=_make_lot_id(tx.transaction_id, tx.asset, adjusted_quantity, tx.timestamp),
            asset=tx.asset,
            acquired_quantity=adjusted_quantity,
            remaining_quantity=adjusted_quantity,
            unit_cost=unit_cost,
            total_cost=total_cost,
            cost_currency=cost_currency,
            acquired_timestamp=tx.timestamp,
            source_transaction_id=tx.transaction_id,
            acquisition_type=acquisition_type,
            fee=tx.fee,
            fee_asset=tx.fee_asset,
            linked_event_id=event.event_id,
        )
        lots.append(lot)
        lot_pool[lot.lot_id] = adjusted_quantity

    def _process_disposal(
        self,
        tx: CanonicalTransaction,
        lot_pool: Dict[str, Decimal],
        events: List[AccountingEvent],
        consumptions: List[LotConsumption],
        all_lots: List[AcquisitionLot],
    ) -> None:
        proceeds, proceeds_currency, warnings = _resolve_proceeds(tx)
        for w in warnings:
            self._warnings.append(w)

        adjusted_proceeds = proceeds
        adjusted_quantity = tx.quantity
        if tx.fee is not None and tx.fee != 0:
            adjusted_proceeds, adjusted_quantity, fee_warnings = apply_disposal_fee(
                proceeds=proceeds,
                quantity=tx.quantity,
                fee=tx.fee,
                fee_asset=tx.fee_asset,
                asset=tx.asset,
                quote_asset=tx.quote_asset,
                source_transaction_id=tx.transaction_id,
            )
            for w in fee_warnings:
                self._warnings.append(w)

        if adjusted_quantity is None or adjusted_quantity <= 0:
            self._warnings.append(
                make_warning(
                    code=WarningCode.ZERO_QUANTITY_DISPOSAL,
                    message=f"Disposal quantity is zero or missing for {tx.transaction_id}",
                    source_transaction_id=tx.transaction_id,
                )
            )
            return

        event = AccountingEvent(
            event_id=_make_event_id(tx.transaction_id, AccountingEventType.DISPOSAL.value),
            event_type=AccountingEventType.DISPOSAL,
            source_transaction_ids=[tx.transaction_id],
            timestamp=tx.timestamp,
            asset=tx.asset,
            quantity=adjusted_quantity,
            proceeds=adjusted_proceeds,
            proceeds_currency=proceeds_currency,
            fee=tx.fee,
            fee_asset=tx.fee_asset,
            metadata={"side": tx.side.value if tx.side else None},
        )
        events.append(event)

        plan = self._method.select_lots(
            available_lots=all_lots,
            lot_remaining=lot_pool,
            disposal_quantity=adjusted_quantity,
            disposal_timestamp=tx.timestamp,
            disposal_transaction_id=tx.transaction_id,
            asset=tx.asset,
            cost_currency=proceeds_currency,
            disposal_proceeds=adjusted_proceeds,
            proceeds_currency=proceeds_currency,
        )
        for err in plan.errors:
            self._errors.append(err)
        for w in plan.warnings:
            self._warnings.append(w)

        for consumption in plan.consumptions:
            currency_mismatch = False
            if consumption.realized_pnl is not None:
                if (
                    consumption.cost_currency is not None
                    and consumption.proceeds_currency is not None
                    and consumption.cost_currency != consumption.proceeds_currency
                ):
                    currency_mismatch = True
                    self._warnings.append(
                        make_warning(
                            code=WarningCode.CURRENCY_MISMATCH,
                            message=f"Currency mismatch for disposal {tx.transaction_id}: cost currency {consumption.cost_currency} != proceeds currency {consumption.proceeds_currency}.",
                            source_transaction_id=tx.transaction_id,
                        )
                    )
                elif (
                    consumption.cost_currency is not None
                    and consumption.proceeds_currency is None
                ):
                    currency_mismatch = True
                    self._warnings.append(
                        make_warning(
                            code=WarningCode.CURRENCY_MISMATCH,
                            message=f"Currency mismatch for disposal {tx.transaction_id}: cost currency {consumption.cost_currency} but proceeds currency is unknown.",
                            source_transaction_id=tx.transaction_id,
                        )
                    )
                elif (
                    consumption.cost_currency is None
                    and consumption.proceeds_currency is not None
                ):
                    currency_mismatch = True
                    self._warnings.append(
                        make_warning(
                            code=WarningCode.CURRENCY_MISMATCH,
                            message=f"Currency mismatch for disposal {tx.transaction_id}: proceeds currency {consumption.proceeds_currency} but cost currency is unknown.",
                            source_transaction_id=tx.transaction_id,
                        )
                    )
            if currency_mismatch:
                consumption = LotConsumption(
                    consumption_id=consumption.consumption_id,
                    lot_id=consumption.lot_id,
                    disposal_event_id=consumption.disposal_event_id,
                    asset=consumption.asset,
                    quantity_consumed=consumption.quantity_consumed,
                    unit_cost=consumption.unit_cost,
                    cost_allocated=consumption.cost_allocated,
                    cost_currency=consumption.cost_currency,
                    disposal_proceeds=consumption.disposal_proceeds,
                    proceeds_currency=consumption.proceeds_currency,
                    realized_pnl=None,
                    pnl_currency=None,
                    consumed_timestamp=consumption.consumed_timestamp,
                )
            consumptions.append(consumption)
            event.linked_lot_ids.append(consumption.lot_id)

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
            events[-1] = AccountingEvent(
                event_id=event.event_id,
                event_type=event.event_type,
                source_transaction_ids=event.source_transaction_ids,
                timestamp=event.timestamp,
                asset=event.asset,
                quantity=event.quantity,
                cost_basis=total_cost_allocated if total_cost_allocated > 0 else None,
                cost_currency=cost_currency,
                proceeds=event.proceeds,
                proceeds_currency=event.proceeds_currency,
                realized_pnl=total_realized_pnl if total_realized_pnl != 0 else None,
                pnl_currency=pnl_currency,
                fee=event.fee,
                fee_asset=event.fee_asset,
                linked_lot_ids=event.linked_lot_ids,
                linked_event_ids=event.linked_event_ids,
                warnings=event.warnings,
                metadata=event.metadata,
            )

        if plan.remaining_quantity > 0:
            self._warnings.append(
                make_warning(
                    code=WarningCode.INSUFFICIENT_LOTS,
                    message=f"Disposal quantity {adjusted_quantity} exceeds available lots for {tx.asset}. Shortage: {plan.shortage}",
                    source_transaction_id=tx.transaction_id,
                    context={"shortage": str(plan.shortage)},
                )
            )

    def _process_deposit(
        self,
        tx: CanonicalTransaction,
        lot_pool: Dict[str, Decimal],
        events: List[AccountingEvent],
        lots: List[AcquisitionLot],
    ) -> None:
        cost_basis, cost_currency, warnings = _resolve_cost_basis(tx)
        for w in warnings:
            self._warnings.append(w)

        adjusted_cost_basis = cost_basis
        adjusted_quantity = tx.quantity
        if tx.fee is not None and tx.fee != 0:
            adjusted_cost_basis, adjusted_quantity, fee_warnings = apply_acquisition_fee(
                cost_basis=cost_basis,
                quantity=tx.quantity,
                fee=tx.fee,
                fee_asset=tx.fee_asset,
                asset=tx.asset,
                quote_asset=tx.quote_asset,
                source_transaction_id=tx.transaction_id,
            )
            for w in fee_warnings:
                self._warnings.append(w)

        acquisition_type = (
            AcquisitionType.DEPOSIT_KNOWN_COST if adjusted_cost_basis is not None else AcquisitionType.DEPOSIT_UNKNOWN_COST
        )

        event = AccountingEvent(
            event_id=_make_event_id(tx.transaction_id, AccountingEventType.ACQUISITION.value),
            event_type=AccountingEventType.ACQUISITION,
            source_transaction_ids=[tx.transaction_id],
            timestamp=tx.timestamp,
            asset=tx.asset,
            quantity=adjusted_quantity,
            cost_basis=adjusted_cost_basis,
            cost_currency=cost_currency,
            fee=tx.fee,
            fee_asset=tx.fee_asset,
            metadata={"acquisition_type": acquisition_type.value},
        )
        events.append(event)

        unit_cost: Optional[Decimal] = None
        total_cost: Optional[Decimal] = None
        if adjusted_cost_basis is not None and adjusted_quantity is not None and adjusted_quantity > 0:
            unit_cost = adjusted_cost_basis / adjusted_quantity
            total_cost = adjusted_cost_basis

        lot = AcquisitionLot(
            lot_id=_make_lot_id(tx.transaction_id, tx.asset, adjusted_quantity, tx.timestamp),
            asset=tx.asset,
            acquired_quantity=adjusted_quantity,
            remaining_quantity=adjusted_quantity,
            unit_cost=unit_cost,
            total_cost=total_cost,
            cost_currency=cost_currency,
            acquired_timestamp=tx.timestamp,
            source_transaction_id=tx.transaction_id,
            acquisition_type=acquisition_type,
            fee=tx.fee,
            fee_asset=tx.fee_asset,
            linked_event_id=event.event_id,
        )
        lots.append(lot)
        lot_pool[lot.lot_id] = adjusted_quantity

    def _process_withdrawal(
        self,
        tx: CanonicalTransaction,
        lot_pool: Dict[str, Decimal],
        events: List[AccountingEvent],
        consumptions: List[LotConsumption],
        all_lots: List[AcquisitionLot],
    ) -> None:
        proceeds = Decimal("0")
        proceeds_currency = None
        if tx.value is not None and tx.value > 0:
            proceeds = tx.value
            proceeds_currency = tx.quote_asset
        elif tx.price is not None and tx.price > 0 and tx.quantity is not None:
            proceeds = tx.price * tx.quantity
            proceeds_currency = tx.quote_asset

        adjusted_quantity = tx.quantity
        if adjusted_quantity is None or adjusted_quantity <= 0:
            self._warnings.append(
                make_warning(
                    code=WarningCode.ZERO_QUANTITY_DISPOSAL,
                    message=f"Withdrawal quantity is zero or missing for {tx.transaction_id}",
                    source_transaction_id=tx.transaction_id,
                )
            )
            return

        event = AccountingEvent(
            event_id=_make_event_id(tx.transaction_id, AccountingEventType.DISPOSAL.value),
            event_type=AccountingEventType.DISPOSAL,
            source_transaction_ids=[tx.transaction_id],
            timestamp=tx.timestamp,
            asset=tx.asset,
            quantity=adjusted_quantity,
            proceeds=proceeds,
            proceeds_currency=proceeds_currency,
            fee=tx.fee,
            fee_asset=tx.fee_asset,
            metadata={"side": None, "withdrawal": True},
        )
        events.append(event)

        if proceeds == 0:
            self._warnings.append(
                make_warning(
                    code=WarningCode.WITHDRAWAL_NO_PROCEEDS,
                    message=f"Withdrawal {tx.transaction_id} for {tx.asset} has no proceeds; cost basis will be computed from lots.",
                    source_transaction_id=tx.transaction_id,
                )
            )

        plan = self._method.select_lots(
            available_lots=all_lots,
            lot_remaining=lot_pool,
            disposal_quantity=adjusted_quantity,
            disposal_timestamp=tx.timestamp,
            disposal_transaction_id=tx.transaction_id,
            asset=tx.asset,
            cost_currency=proceeds_currency,
            disposal_proceeds=proceeds,
            proceeds_currency=proceeds_currency,
        )
        for err in plan.errors:
            self._errors.append(err)
        for w in plan.warnings:
            self._warnings.append(w)

        for consumption in plan.consumptions:
            consumptions.append(consumption)
            lot_pool[consumption.lot_id] = lot_pool.get(consumption.lot_id, Decimal("0")) - consumption.quantity_consumed

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
            events[-1] = AccountingEvent(
                event_id=event.event_id,
                event_type=event.event_type,
                source_transaction_ids=event.source_transaction_ids,
                timestamp=event.timestamp,
                asset=event.asset,
                quantity=event.quantity,
                cost_basis=total_cost_allocated if total_cost_allocated > 0 else None,
                cost_currency=cost_currency,
                proceeds=event.proceeds,
                proceeds_currency=event.proceeds_currency,
                realized_pnl=total_realized_pnl if total_realized_pnl != 0 else None,
                pnl_currency=pnl_currency,
                fee=event.fee,
                fee_asset=event.fee_asset,
                linked_lot_ids=event.linked_lot_ids,
                linked_event_ids=event.linked_event_ids,
                warnings=event.warnings,
                metadata=event.metadata,
            )

    def _process_unknown(self, tx: CanonicalTransaction, events: List[AccountingEvent]) -> None:
        event = AccountingEvent(
            event_id=_make_event_id(tx.transaction_id, AccountingEventType.NON_ACCOUNTING.value),
            event_type=AccountingEventType.NON_ACCOUNTING,
            source_transaction_ids=[tx.transaction_id],
            timestamp=tx.timestamp,
            asset=tx.asset,
            quantity=tx.quantity or Decimal("0"),
            metadata={"reason": "unknown transaction type; no accounting effect"},
        )
        events.append(event)
        self._warnings.append(
            make_warning(
                code=WarningCode.UNKNOWN_TRANSACTION_TYPE,
                message=f"Transaction {tx.transaction_id} has type UNKNOWN and is not part of a matched convert.",
                source_transaction_id=tx.transaction_id,
            )
        )


def _resolve_cost_basis(
    tx: CanonicalTransaction,
) -> Tuple[Optional[Decimal], Optional[str], List[AccountingWarning]]:
    warnings: List[AccountingWarning] = []
    cost_basis: Optional[Decimal] = None
    cost_currency: Optional[str] = tx.quote_asset

    if tx.value is not None:
        cost_basis = tx.value
    elif tx.price is not None and tx.quantity is not None:
        cost_basis = tx.price * tx.quantity
        cost_currency = tx.quote_asset
    else:
        warnings.append(
            make_warning(
                code=WarningCode.MISSING_COST_BASIS,
                message=f"Transaction {tx.transaction_id} for {tx.asset} has no price or value; cost basis is unknown.",
                source_transaction_id=tx.transaction_id,
            )
        )

    return cost_basis, cost_currency, warnings


def _resolve_proceeds(
    tx: CanonicalTransaction,
) -> Tuple[Optional[Decimal], Optional[str], List[AccountingWarning]]:
    warnings: List[AccountingWarning] = []
    proceeds: Optional[Decimal] = None
    proceeds_currency: Optional[str] = tx.quote_asset

    if tx.value is not None:
        proceeds = tx.value
    elif tx.price is not None and tx.quantity is not None:
        proceeds = tx.price * tx.quantity
        proceeds_currency = tx.quote_asset
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
    raw = "|".join(sorted([tx_id, event_type]))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _make_lot_id(tx_id: str, asset: str, quantity: Decimal, timestamp: datetime) -> str:
    raw = "|".join(sorted([tx_id, asset, str(quantity), timestamp.isoformat()]))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _make_pnl_id(consumption_ids: List[str], currency: str, from_ts: datetime, to_ts: datetime) -> str:
    raw = "|".join(sorted([*consumption_ids, currency, str(from_ts), str(to_ts)]))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
