from __future__ import annotations

from decimal import Decimal
from typing import List, Optional, Tuple

from backend.accounting.models import WarningCode
from backend.accounting.exceptions import make_warning


def apply_acquisition_fee(
    cost_basis: Optional[Decimal],
    quantity: Optional[Decimal],
    fee: Optional[Decimal],
    fee_asset: Optional[str],
    asset: str,
    quote_asset: Optional[str],
    source_transaction_id: Optional[str] = None,
) -> Tuple[Optional[Decimal], Optional[Decimal], List]:
    warnings = []
    if fee is None or fee == 0:
        return cost_basis, quantity, warnings

    if fee_asset == quote_asset:
        if cost_basis is not None:
            adjusted_cost = cost_basis + fee
            return adjusted_cost, quantity, warnings
        warnings.append(
            make_warning(
                code=WarningCode.THIRD_ASSET_FEE,
                message=f"Fee {fee} in quote asset {quote_asset} cannot be allocated: acquisition cost basis is unknown for {asset}.",
                source_transaction_id=source_transaction_id,
            )
        )
        return cost_basis, quantity, warnings
    elif fee_asset == asset:
        if quantity is not None and quantity > fee:
            adjusted_quantity = quantity - fee
            return cost_basis, adjusted_quantity, warnings
        else:
            warnings.append(
                make_warning(
                    code=WarningCode.THIRD_ASSET_FEE,
                    message=f"Base-asset fee {fee} exceeds quantity {quantity} for {asset}.",
                    source_transaction_id=source_transaction_id,
                )
            )
            return cost_basis, quantity, warnings
    else:
        if fee_asset:
            warnings.append(
                make_warning(
                    code=WarningCode.THIRD_ASSET_FEE,
                    message=f"Fee asset {fee_asset} is not the quote asset or base asset for {asset}.",
                    source_transaction_id=source_transaction_id,
                )
            )
        else:
            warnings.append(
                make_warning(
                    code=WarningCode.MISSING_FEE_ASSET,
                    message=f"Fee asset is missing for fee {fee} on {asset}.",
                    source_transaction_id=source_transaction_id,
                )
            )
        return cost_basis, quantity, warnings


def apply_disposal_fee(
    proceeds: Optional[Decimal],
    quantity: Optional[Decimal],
    fee: Optional[Decimal],
    fee_asset: Optional[str],
    asset: str,
    quote_asset: Optional[str],
    source_transaction_id: Optional[str] = None,
) -> Tuple[Optional[Decimal], Optional[Decimal], List]:
    warnings = []
    if fee is None or fee == 0:
        return proceeds, quantity, warnings

    if fee_asset == quote_asset:
        if proceeds is not None:
            adjusted_proceeds = proceeds - fee
            return adjusted_proceeds, quantity, warnings
        warnings.append(
            make_warning(
                code=WarningCode.THIRD_ASSET_FEE,
                message=f"Fee {fee} in quote asset {quote_asset} cannot be allocated: disposal proceeds are unknown for {asset}.",
                source_transaction_id=source_transaction_id,
            )
        )
        return proceeds, quantity, warnings
    elif fee_asset == asset:
        if quantity is not None and quantity > fee:
            adjusted_quantity = quantity - fee
            return proceeds, adjusted_quantity, warnings
        else:
            warnings.append(
                make_warning(
                    code=WarningCode.THIRD_ASSET_FEE,
                    message=f"Base-asset fee {fee} exceeds quantity {quantity} for {asset}.",
                    source_transaction_id=source_transaction_id,
                )
            )
            return proceeds, quantity, warnings
    else:
        if fee_asset:
            warnings.append(
                make_warning(
                    code=WarningCode.THIRD_ASSET_FEE,
                    message=f"Fee asset {fee_asset} is not the quote asset or base asset for {asset}.",
                    source_transaction_id=source_transaction_id,
                )
            )
        else:
            warnings.append(
                make_warning(
                    code=WarningCode.MISSING_FEE_ASSET,
                    message=f"Fee asset is missing for fee {fee} on {asset}.",
                    source_transaction_id=source_transaction_id,
                )
            )
        return proceeds, quantity, warnings
