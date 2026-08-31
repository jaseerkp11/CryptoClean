from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Optional

from backend.models.transaction import CanonicalTransaction, Source, TransactionType
from backend.reconciliation.transfers import TransferLeg, TransferRules


# Observed Binance internal-transfer operations and the internal accounts they
# connect. Order inside the tuple is irrelevant for compatibility; the set of
# two accounts must match exactly.
BINANCE_TRANSFER_OPERATIONS: dict[str, tuple[str, str]] = {
    "Transfer Between Spot and UM Futures": ("Spot", "USD-M Futures"),
    "Transfer Between UM Futures and Funding": ("USD-M Futures", "Funding"),
    "Transfer Between Spot and Funding": ("Spot", "Funding"),
}


class BinanceTransferRules(TransferRules):
    def extract_leg(self, tx: CanonicalTransaction) -> Optional[TransferLeg]:
        if tx.transaction_type != TransactionType.TRANSFER:
            return None
        meta = tx.metadata or {}
        account = meta.get("source_account")
        operation = meta.get("source_operation")
        signed_raw = meta.get("source_change_signed")
        if signed_raw is None or tx.quantity is None:
            return None
        try:
            signed = Decimal(str(signed_raw))
        except (InvalidOperation, ValueError):
            return None
        source_value = tx.source.value if isinstance(tx.source, Source) else str(tx.source)
        return TransferLeg(
            transaction_id=tx.transaction_id,
            source=source_value,
            asset=tx.asset,
            quantity=tx.quantity,
            signed_amount=signed,
            account=account,
            operation=operation,
            timestamp=tx.timestamp,
            transaction_type=tx.transaction_type,
            tx_hash=tx.tx_hash,
        )

    def accounts_compatible(self, a: TransferLeg, b: TransferLeg) -> bool:
        pair_a = BINANCE_TRANSFER_OPERATIONS.get(a.operation)
        pair_b = BINANCE_TRANSFER_OPERATIONS.get(b.operation)
        if not pair_a or not pair_b:
            return False
        # The two legs must belong to the same transfer operation type.
        if a.operation != b.operation:
            return False
        if not a.account or not b.account:
            return False
        # The account pair must match the canonical account pair (order-independent).
        return {a.account, b.account} == set(pair_a)
