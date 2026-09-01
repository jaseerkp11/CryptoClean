from __future__ import annotations

import hashlib
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from zoneinfo import ZoneInfo

from backend.adapters.base import BaseAdapter, AdapterResult
from backend.models.transaction import CanonicalTransaction, Source, TransactionType


class BinanceTransactionRecordAdapter(BaseAdapter):
    REQUIRED_COLUMNS = {"User ID", "Time", "Account", "Operation", "Coin", "Change", "Remark"}

    def __init__(self, timezone: Optional[str] = None):
        self.timezone = None
        if timezone:
            try:
                self.timezone = ZoneInfo(timezone)
            except Exception as exc:
                raise ValueError(f"Invalid timezone: {timezone}") from exc

    def _validate_columns(self, rows: List[Dict[str, Any]]) -> Optional[str]:
        if not rows:
            return "No rows provided."
        actual = set(rows[0].keys())
        missing = self.REQUIRED_COLUMNS - actual
        if missing:
            return f"Missing required columns: {', '.join(sorted(missing))}"
        return None

    def _parse_timestamp(self, time_str: str) -> datetime:
        cleaned = time_str.strip()
        try:
            parsed = datetime.fromisoformat(cleaned)
            if parsed.tzinfo is not None:
                return parsed
        except ValueError:
            pass
        try:
            naive = datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise ValueError(f"Invalid Binance timestamp: {time_str}") from exc
        if self.timezone is not None:
            return naive.replace(tzinfo=self.timezone)
        return naive.replace(tzinfo=ZoneInfo("UTC"))

    def _parse_change(self, change_str: str) -> Decimal:
        try:
            return Decimal(change_str.strip())
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Invalid Binance Change: {change_str}") from exc

    def _extract_trade_id(self, remark: Optional[str]) -> Optional[str]:
        if not remark:
            return None
        match = re.search(r"TradeID\s*-\s*(\S+)", remark)
        if match:
            return match.group(1)
        return None

    def _extract_p2p_id(self, remark: Optional[str]) -> Optional[str]:
        if not remark:
            return None
        match = re.search(r"P2P\s*-\s*(\S+)", remark)
        if match:
            return match.group(1)
        return None

    def _compute_transaction_id(
        self,
        account: str,
        time: str,
        operation: str,
        coin: str,
        change: str,
        remark: Optional[str],
    ) -> str:
        raw = f"binance|{account}|{time}|{operation}|{coin}|{change}|{remark or ''}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def _map_operation(self, operation: str) -> tuple[TransactionType, Optional[Side], str]:
        op = operation.strip()

        if op == "Deposit":
            return TransactionType.DEPOSIT, None, ""

        if op == "Binance Convert":
            return (
                TransactionType.UNKNOWN,
                None,
                "Binance Convert rows should be grouped later.",
            )

        if op in {
            "Transfer Between Spot and UM Futures",
            "Transfer Between UM Futures and Funding",
            "Transfer Between Spot and Funding",
        }:
            return TransactionType.TRANSFER, None, ""

        if op == "Fee":
            return TransactionType.FEE, None, ""

        if op == "Funding Fee":
            return TransactionType.FEE, None, "Funding Fee preserved in metadata."

        if op == "Realized Profit and Loss":
            return (
                TransactionType.UNKNOWN,
                None,
                "Realized P&L requires a dedicated canonical type.",
            )

        if op == "P2P Trading":
            return TransactionType.UNKNOWN, None, "P2P Trading requires a dedicated parser."

        if op == "Crypto Box":
            return TransactionType.REWARD, None, ""

        if op == "Asset Recovery":
            return TransactionType.UNKNOWN, None, ""

        if op == "Simple Earn Flexible Subscription":
            return TransactionType.TRANSFER, None, ""

        if op == "Insurance Fund Refund":
            return TransactionType.UNKNOWN, None, ""

        return TransactionType.UNKNOWN, None, f"Unrecognized Binance operation: {op}"

    def adapt(self, rows: List[Dict[str, Any]]) -> AdapterResult:
        column_error = self._validate_columns(rows)
        if column_error:
            return AdapterResult(transactions=[], warnings=[], errors=[column_error])

        transactions: List[CanonicalTransaction] = []
        warnings: List[str] = []
        errors: List[str] = []

        for row in rows:
            try:
                user_id = row.get("User ID")
                time_str = row["Time"]
                account = row["Account"]
                operation = row["Operation"]
                coin = row["Coin"]
                change_str = row["Change"]
                remark = row.get("Remark")

                timestamp = self._parse_timestamp(time_str)
                change = self._parse_change(change_str)

                tx_type, side, op_warning = self._map_operation(operation)
                if op_warning:
                    warnings.append(op_warning)

                quantity = abs(change)

                source_tx_id = self._extract_trade_id(remark)
                if not source_tx_id:
                    source_tx_id = self._extract_p2p_id(remark)

                metadata: Dict[str, Any] = {
                    "source": "binance",
                    "source_account": account,
                    "source_operation": operation,
                    "source_remark": remark,
                    "source_change_signed": str(change),
                }
                metadata.pop("User ID", None)
                metadata.pop("user_id", None)

                tx_id = self._compute_transaction_id(
                    account, time_str, operation, coin, change_str, remark
                )

                tx = CanonicalTransaction(
                    transaction_id=tx_id,
                    source=Source.BINANCE,
                    source_transaction_id=source_tx_id,
                    timestamp=timestamp,
                    transaction_type=tx_type,
                    side=side,
                    asset=coin,
                    quantity=quantity,
                    confidence=1.0,
                    metadata=metadata,
                )
                transactions.append(tx)
            except Exception as exc:
                errors.append(f"Failed to adapt row: {exc}")

        return AdapterResult(transactions=transactions, warnings=warnings, errors=errors)
