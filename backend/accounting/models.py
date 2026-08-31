from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AccountingEventType(str, Enum):
    ACQUISITION = "ACQUISITION"
    DISPOSAL = "DISPOSAL"
    TRANSFER = "TRANSFER"
    SWAP = "SWAP"
    FEE = "FEE"
    NON_ACCOUNTING = "NON_ACCOUNTING"


class AcquisitionType(str, Enum):
    BUY = "BUY"
    SWAP_IN = "SWAP_IN"
    DEPOSIT_KNOWN_COST = "DEPOSIT_KNOWN_COST"
    DEPOSIT_UNKNOWN_COST = "DEPOSIT_UNKNOWN_COST"
    OTHER = "OTHER"


class WarningCode(str, Enum):
    MISSING_COST_BASIS = "MISSING_COST_BASIS"
    MISSING_PROCEEDS = "MISSING_PROCEEDS"
    INSUFFICIENT_LOTS = "INSUFFICIENT_LOTS"
    UNRESOLVED_ASSET = "UNRESOLVED_ASSET"
    MISSING_QUOTE_ASSET = "MISSING_QUOTE_ASSET"
    MISSING_FEE_ASSET = "MISSING_FEE_ASSET"
    ZERO_QUANTITY_DISPOSAL = "ZERO_QUANTITY_DISPOSAL"
    PARTIAL_SWAP_VALUATION = "PARTIAL_SWAP_VALUATION"
    UNMATCHED_TRANSFER = "UNMATCHED_TRANSFER"
    UNKNOWN_TRANSACTION_TYPE = "UNKNOWN_TRANSACTION_TYPE"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    THIRD_ASSET_FEE = "THIRD_ASSET_FEE"
    WITHDRAWAL_NO_PROCEEDS = "WITHDRAWAL_NO_PROCEEDS"
    MISSING_CONVERT_LINK = "MISSING_CONVERT_LINK"


class ExceptionCode(str, Enum):
    INSUFFICIENT_LOTS_FOR_DISPOSAL = "INSUFFICIENT_LOTS_FOR_DISPOSAL"
    NEGATIVE_LOT_REMAINING = "NEGATIVE_LOT_REMAINING"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    INVALID_COST = "INVALID_COST"


class AccountingWarning(BaseModel):
    model_config = ConfigDict(frozen=True)

    warning_id: str
    code: WarningCode
    message: str
    source_transaction_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


class AccountingException(BaseModel):
    model_config = ConfigDict(frozen=True)

    exception_id: str
    code: ExceptionCode
    message: str
    source_transaction_id: Optional[str] = None


class AccountingEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    event_type: AccountingEventType
    source_transaction_ids: List[str]
    timestamp: datetime
    asset: str
    quantity: Decimal
    cost_basis: Optional[Decimal] = None
    cost_currency: Optional[str] = None
    proceeds: Optional[Decimal] = None
    proceeds_currency: Optional[str] = None
    realized_pnl: Optional[Decimal] = None
    pnl_currency: Optional[str] = None
    fee: Optional[Decimal] = None
    fee_asset: Optional[str] = None
    linked_lot_ids: List[str] = []
    linked_event_ids: List[str] = []
    warnings: List[AccountingWarning] = []
    metadata: Optional[Dict[str, Any]] = None

    @field_validator("quantity", mode="before")
    @classmethod
    def quantity_positive(cls, v: Any) -> Any:
        if v is None:
            return v
        d = Decimal(str(v)) if not isinstance(v, Decimal) else v
        if d <= 0:
            raise ValueError("quantity must be positive.")
        return d

    @field_validator("cost_basis", "proceeds", "realized_pnl", "fee", mode="before")
    @classmethod
    def decimal_not_nan_or_inf(cls, v: Any) -> Any:
        if v is None:
            return v
        if isinstance(v, Decimal):
            if v.is_nan() or v.is_infinite():
                raise ValueError("Decimal value must not be NaN or infinite.")
            return v
        d = Decimal(str(v))
        if d.is_nan() or d.is_infinite():
            raise ValueError("Decimal value must not be NaN or infinite.")
        return d


class AcquisitionLot(BaseModel):
    model_config = ConfigDict(frozen=True)

    lot_id: str
    asset: str
    acquired_quantity: Decimal
    remaining_quantity: Decimal
    unit_cost: Optional[Decimal] = None
    total_cost: Optional[Decimal] = None
    cost_currency: Optional[str] = None
    acquired_timestamp: datetime
    source_transaction_id: str
    acquisition_type: AcquisitionType
    fee: Optional[Decimal] = None
    fee_asset: Optional[str] = None
    linked_event_id: str

    @field_validator("acquired_quantity", "remaining_quantity", mode="before")
    @classmethod
    def quantity_non_negative(cls, v: Any) -> Any:
        if v is None:
            return v
        d = Decimal(str(v)) if not isinstance(v, Decimal) else v
        if d < 0:
            raise ValueError("quantity must not be negative.")
        return d

    @field_validator("unit_cost", "total_cost", "fee", mode="before")
    @classmethod
    def cost_non_negative(cls, v: Any) -> Any:
        if v is None:
            return v
        d = Decimal(str(v)) if not isinstance(v, Decimal) else v
        if d < 0:
            raise ValueError("cost must not be negative.")
        return d

    @model_validator(mode="after")
    def validate_remaining(self) -> AcquisitionLot:
        if self.remaining_quantity > self.acquired_quantity:
            raise ValueError("remaining_quantity cannot exceed acquired_quantity.")
        return self


class LotConsumption(BaseModel):
    model_config = ConfigDict(frozen=True)

    consumption_id: str
    lot_id: str
    disposal_event_id: str
    asset: str
    quantity_consumed: Decimal
    unit_cost: Optional[Decimal] = None
    cost_allocated: Optional[Decimal] = None
    cost_currency: Optional[str] = None
    disposal_proceeds: Optional[Decimal] = None
    proceeds_currency: Optional[str] = None
    realized_pnl: Optional[Decimal] = None
    pnl_currency: Optional[str] = None
    consumed_timestamp: datetime

    @field_validator("quantity_consumed", mode="before")
    @classmethod
    def quantity_positive(cls, v: Any) -> Any:
        if v is None:
            return v
        d = Decimal(str(v)) if not isinstance(v, Decimal) else v
        if d <= 0:
            raise ValueError("quantity_consumed must be positive.")
        return d

    @field_validator("unit_cost", "cost_allocated", "disposal_proceeds", "realized_pnl", mode="before")
    @classmethod
    def decimal_not_nan_or_inf(cls, v: Any) -> Any:
        if v is None:
            return v
        if isinstance(v, Decimal):
            if v.is_nan() or v.is_infinite():
                raise ValueError("Decimal value must not be NaN or infinite.")
            return v
        d = Decimal(str(v))
        if d.is_nan() or d.is_infinite():
            raise ValueError("Decimal value must not be NaN or infinite.")
        return d


class RealizedPnL(BaseModel):
    model_config = ConfigDict(frozen=True)

    pnl_id: str
    asset: str
    total_realized_pnl: Decimal
    currency: str
    consumption_ids: List[str]
    lot_ids: List[str]
    event_ids: List[str]
    from_timestamp: datetime
    to_timestamp: datetime

    @field_validator("total_realized_pnl", mode="before")
    @classmethod
    def pnl_decimal(cls, v: Any) -> Any:
        if isinstance(v, Decimal):
            if v.is_nan() or v.is_infinite():
                raise ValueError("P&L must not be NaN or infinite.")
            return v
        d = Decimal(str(v))
        if d.is_nan() or d.is_infinite():
            raise ValueError("P&L must not be NaN or infinite.")
        return d


class AccountingSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_events: int = 0
    acquisition_events: int = 0
    disposal_events: int = 0
    transfer_events: int = 0
    swap_events: int = 0
    total_lots_created: int = 0
    total_lots_consumed: int = 0
    total_realized_pnl: Optional[Decimal] = None
    pnl_currency: Optional[str] = None
    warnings_count: int = 0
    errors_count: int = 0


class AccountingResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    events: List[AccountingEvent] = []
    lots: List[AcquisitionLot] = []
    consumptions: List[LotConsumption] = []
    realized_pnl: List[RealizedPnL] = []
    warnings: List[AccountingWarning] = []
    errors: List[AccountingException] = []
    summary: AccountingSummary = AccountingSummary()
