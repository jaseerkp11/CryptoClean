from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Optional

from backend.models.transaction import CanonicalTransaction, Source, TransactionType
from backend.reconciliation.converts import ConvertLeg, ConvertRules


BINANCE_CONVERT_OPERATION = "Binance Convert"
BINANCE_SMALL_ASSETS_EXCHANGE_OPERATIONS = {
    "Small Assets Exchange BNB",
    "Small Assets Exchange",
}
BINANCE_TOKEN_SWAP_REDENOMINATION = "Token Swap - Redenomination/Rebranding"


class BinanceConvertRules(ConvertRules):
    def extract_leg(self, tx: CanonicalTransaction) -> Optional[ConvertLeg]:
        if tx.transaction_type != TransactionType.UNKNOWN:
            return None
        meta = tx.metadata or {}
        source_operation = meta.get("source_operation")
        if source_operation not in {
            BINANCE_CONVERT_OPERATION,
            *BINANCE_SMALL_ASSETS_EXCHANGE_OPERATIONS,
            BINANCE_TOKEN_SWAP_REDENOMINATION,
        }:
            return None
        signed_raw = meta.get("source_change_signed")
        if signed_raw is None or tx.quantity is None:
            return None
        try:
            signed = Decimal(str(signed_raw))
        except (InvalidOperation, ValueError):
            return None
        if signed == 0:
            return None
        source_value = tx.source.value if isinstance(tx.source, Source) else str(tx.source)
        return ConvertLeg(
            transaction_id=tx.transaction_id,
            source=source_value,
            account=str(meta.get("source_account", "")),
            asset=tx.asset,
            quantity=tx.quantity,
            signed_amount=signed,
            timestamp=tx.timestamp,
            operation=source_operation,
        )
