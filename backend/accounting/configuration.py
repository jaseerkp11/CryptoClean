from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.accounting.models import AcquisitionType, AccountingEventType


class CostBasisMethodType(str, Enum):
    FIFO = "FIFO"
    LIFO = "LIFO"
    HIFO = "HIFO"
    SPECIFIC_IDENTIFICATION = "SPECIFIC_IDENTIFICATION"


class FeeAllocationPolicy(str, Enum):
    ADJUST_ACQUISITION_COST = "ADJUST_ACQUISITION_COST"
    REDUCE_ACQUISITION_QUANTITY = "REDUCE_ACQUISITION_QUANTITY"
    RECORD_SEPARATE_FEE = "RECORD_SEPARATE_FEE"


class MissingCostBasisPolicy(str, Enum):
    CREATE_LOT_WITH_NULL_COST = "CREATE_LOT_WITH_NULL_COST"
    SKIP_ACQUISITION = "SKIP_ACQUISITION"


class AccountingConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    cost_basis_method: CostBasisMethodType = CostBasisMethodType.FIFO
    reporting_currency: Optional[str] = None
    timezone: str = "UTC"
    fee_allocation_policy: FeeAllocationPolicy = FeeAllocationPolicy.ADJUST_ACQUISITION_COST
    missing_cost_basis_policy: MissingCostBasisPolicy = MissingCostBasisPolicy.CREATE_LOT_WITH_NULL_COST
    transfer_preserves_lots: bool = True
    require_matching_transfer_for_lot_preservation: bool = True

    @field_validator("cost_basis_method")
    @classmethod
    def validate_method(cls, v: CostBasisMethodType) -> CostBasisMethodType:
        return v

    @field_validator("reporting_currency")
    @classmethod
    def validate_currency(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("reporting_currency must not be blank.")
        return v.upper() if v else v
