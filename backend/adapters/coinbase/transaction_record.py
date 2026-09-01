from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from zoneinfo import ZoneInfo

from backend.adapters.base import BaseAdapter, AdapterResult
from backend.models.transaction import CanonicalTransaction, Source, Side, TransactionType


class CoinbaseTransactionRecordAdapter(BaseAdapter):
    REQUIRED_COLUMNS = {"Timestamp", "Transaction Type", "Asset", "Quantity Transacted"}

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

    def _parse_timestamp(self, value: str) -> datetime:
        cleaned = value.strip()
        for fmt in (
            "%Y-%m-%d %H:%M:%S %Z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
        ):
            try:
                naive = datetime.strptime(cleaned, fmt)
            except ValueError:
                continue
            if naive.tzinfo is not None:
                return naive
            if self.timezone is not None:
                return naive.replace(tzinfo=self.timezone)
            return naive.replace(tzinfo=ZoneInfo("UTC"))
        raise ValueError(f"Invalid Coinbase Timestamp: {value}")

    def _parse_decimal(self, value: Any, field_name: str) -> Decimal:
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(f"Missing {field_name}.")
        s = str(value).strip()
        try:
            d = Decimal(s)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Invalid Decimal for {field_name}: {s}") from exc
        if d.is_nan() or d.is_infinite():
            raise ValueError(f"{field_name} must not be NaN or infinite.")
        return d

    def _map_transaction_type(self, raw: str) -> tuple[TransactionType, Optional[Side]]:
        op = raw.strip().lower()
        if op == "buy":
            return TransactionType.TRADE, Side.BUY
        if op == "sell":
            return TransactionType.TRADE, Side.SELL
        if op == "send":
            return TransactionType.WITHDRAWAL, None
        if op == "receive":
            return TransactionType.DEPOSIT, None
        if op == "convert":
            return TransactionType.SWAP, None
        return TransactionType.UNKNOWN, None

    def _compute_transaction_id(
        self,
        timestamp_str: str,
        transaction_type: str,
        asset: str,
        quantity_str: str,
        subtotal_str: Optional[str],
    ) -> str:
        raw = f"coinbase|{timestamp_str}|{transaction_type}|{asset}|{quantity_str}|{subtotal_str or ''}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def adapt(self, rows: List[Dict[str, Any]]) -> AdapterResult:
        column_error = self._validate_columns(rows)
        if column_error:
            return AdapterResult(transactions=[], warnings=[], errors=[column_error])

        transactions: List[CanonicalTransaction] = []
        warnings: List[str] = []
        errors: List[str] = []

        for row in rows:
            try:
                timestamp_str = row["Timestamp"]
                transaction_type_str = row["Transaction Type"]
                asset = row["Asset"]
                quantity_str = row["Quantity Transacted"]

                spot_price_currency = row.get("Spot Price Currency")
                spot_price_str = row.get("Spot Price at Transaction")
                subtotal_str = row.get("Subtotal")
                total_str = row.get("Total (inclusive of fees)")
                fee_str = row.get("Fees")
                notes = row.get("Notes")

                timestamp = self._parse_timestamp(timestamp_str)
                quantity = self._parse_decimal(quantity_str, "Quantity Transacted")

                if quantity <= 0:
                    raise ValueError(f"Quantity Transacted must be positive: {quantity}")

                tx_type, side = self._map_transaction_type(transaction_type_str)

                price = None
                quote_asset = None
                if spot_price_str is not None and str(spot_price_str).strip():
                    try:
                        price = Decimal(str(spot_price_str).strip().replace(",", ""))
                        if price.is_nan() or price.is_infinite():
                            warnings.append(f"Spot Price is NaN or infinite: {spot_price_str}")
                            price = None
                    except (InvalidOperation, ValueError):
                        warnings.append(f"Invalid Spot Price: {spot_price_str}")
                        price = None
                if spot_price_currency is not None and str(spot_price_currency).strip():
                    quote_asset = str(spot_price_currency).strip().upper()

                value = None
                if total_str is not None and str(total_str).strip():
                    try:
                        value = Decimal(str(total_str).strip().replace(",", ""))
                        if value.is_nan() or value.is_infinite():
                            warnings.append(f"Total is NaN or infinite: {total_str}")
                            value = None
                    except (InvalidOperation, ValueError):
                        warnings.append(f"Invalid Total: {total_str}")
                        value = None
                elif subtotal_str is not None and str(subtotal_str).strip():
                    try:
                        value = Decimal(str(subtotal_str).strip().replace(",", ""))
                        if value.is_nan() or value.is_infinite():
                            warnings.append(f"Subtotal is NaN or infinite: {subtotal_str}")
                            value = None
                    except (InvalidOperation, ValueError):
                        warnings.append(f"Invalid Subtotal: {subtotal_str}")
                        value = None

                if value is None and price is not None:
                    try:
                        value = quantity * price
                    except Exception:
                        value = None

                fee = None
                if fee_str is not None and str(fee_str).strip():
                    try:
                        fee = Decimal(str(fee_str).strip().replace(",", ""))
                        if fee.is_nan() or fee.is_infinite():
                            warnings.append(f"Fee is NaN or infinite: {fee_str}")
                            fee = None
                    except (InvalidOperation, ValueError):
                        warnings.append(f"Invalid Fee: {fee_str}")
                        fee = None

                metadata: Dict[str, Any] = {
                    "source": "coinbase",
                    "source_report_type": "transaction_record",
                    "source_timestamp": timestamp_str,
                    "source_transaction_type": transaction_type_str,
                    "source_quantity": quantity_str,
                }
                if spot_price_currency:
                    metadata["source_spot_price_currency"] = spot_price_currency
                if spot_price_str:
                    metadata["source_spot_price"] = str(spot_price_str)
                if subtotal_str:
                    metadata["source_subtotal"] = str(subtotal_str)
                if total_str:
                    metadata["source_total"] = str(total_str)
                if fee_str:
                    metadata["source_fee"] = str(fee_str)
                if notes:
                    metadata["source_remark"] = str(notes)

                tx_id = self._compute_transaction_id(
                    timestamp_str,
                    transaction_type_str,
                    asset,
                    quantity_str,
                    subtotal_str,
                )

                tx = CanonicalTransaction(
                    transaction_id=tx_id,
                    source=Source.COINBASE,
                    timestamp=timestamp,
                    transaction_type=tx_type,
                    side=side,
                    asset=asset,
                    quantity=quantity,
                    quote_asset=quote_asset,
                    price=price,
                    value=value,
                    fee=fee,
                    confidence=1.0,
                    metadata=metadata,
                )
                transactions.append(tx)
            except Exception as exc:
                errors.append(f"Failed to adapt Coinbase row: {exc}")

        return AdapterResult(transactions=transactions, warnings=warnings, errors=errors)
