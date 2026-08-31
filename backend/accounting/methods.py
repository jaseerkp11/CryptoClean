from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, List, Optional

from backend.accounting.models import AcquisitionLot, LotConsumption
from backend.accounting.exceptions import make_exception, ExceptionCode, WarningCode


class ConsumptionPlan:
    def __init__(self):
        self.consumptions: List[LotConsumption] = []
        self.remaining_quantity: Decimal = Decimal("0")
        self.warnings: List = []
        self.errors: List = []
        self.shortage: Decimal = Decimal("0")


class CostBasisMethod(ABC):
    @abstractmethod
    def select_lots(
        self,
        available_lots: List[AcquisitionLot],
        lot_remaining: Dict[str, Decimal],
        disposal_quantity: Decimal,
        disposal_timestamp,
        disposal_transaction_id: str,
        asset: str,
        cost_currency: Optional[str],
        disposal_proceeds: Optional[Decimal] = None,
        proceeds_currency: Optional[str] = None,
    ) -> ConsumptionPlan:
        ...


class FIFOMethod(CostBasisMethod):
    def select_lots(
        self,
        available_lots: List[AcquisitionLot],
        lot_remaining: Dict[str, Decimal],
        disposal_quantity: Decimal,
        disposal_timestamp,
        disposal_transaction_id: str,
        asset: str,
        cost_currency: Optional[str],
        disposal_proceeds: Optional[Decimal] = None,
        proceeds_currency: Optional[str] = None,
    ) -> ConsumptionPlan:
        plan = ConsumptionPlan()
        remaining = disposal_quantity
        asset_lots = [lot for lot in available_lots if lot.asset == asset]
        sorted_lots = sorted(
            asset_lots,
            key=lambda lot: (
                lot.acquired_timestamp,
                lot.lot_id,
            ),
        )
        for lot in sorted_lots:
            if remaining <= 0:
                break
            available = lot_remaining.get(lot.lot_id, Decimal("0"))
            if available <= 0:
                continue
            consumed = min(remaining, available)
            cost_allocated = Decimal("0")
            if lot.unit_cost is not None:
                cost_allocated = consumed * lot.unit_cost
            lot_proceeds = Decimal("0")
            lot_pnl = Decimal("0")
            if disposal_proceeds is not None and disposal_quantity > 0:
                lot_proceeds = (disposal_proceeds / disposal_quantity) * consumed
                lot_pnl = lot_proceeds - cost_allocated
            consumption = LotConsumption(
                consumption_id=_make_consumption_id(lot.lot_id, disposal_transaction_id, consumed),
                lot_id=lot.lot_id,
                disposal_event_id=disposal_transaction_id,
                asset=asset,
                quantity_consumed=consumed,
                unit_cost=lot.unit_cost,
                cost_allocated=cost_allocated,
                cost_currency=lot.cost_currency,
                disposal_proceeds=lot_proceeds,
                proceeds_currency=proceeds_currency,
                realized_pnl=lot_pnl,
                pnl_currency=proceeds_currency,
                consumed_timestamp=disposal_timestamp,
            )
            plan.consumptions.append(consumption)
            remaining -= consumed
            lot_remaining[lot.lot_id] = available - consumed
        plan.remaining_quantity = remaining
        if remaining > 0:
            plan.shortage = remaining
            plan.errors.append(
                make_exception(
                    code=ExceptionCode.INSUFFICIENT_LOTS_FOR_DISPOSAL,
                    message=f"Insufficient lots for disposal of {disposal_quantity} {asset}. Shortage: {remaining} {asset}",
                    source_transaction_id=disposal_transaction_id,
                )
            )
        return plan


def _make_consumption_id(lot_id: str, disposal_tx_id: str, quantity: Decimal) -> str:
    import hashlib

    raw = "|".join(sorted([lot_id, disposal_tx_id, str(quantity)]))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
