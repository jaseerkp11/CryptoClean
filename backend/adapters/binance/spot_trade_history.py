from __future__ import annotations

import hashlib
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from zoneinfo import ZoneInfo

from backend.adapters.base import BaseAdapter, AdapterResult
from backend.models.transaction import CanonicalTransaction, Source, Side, TransactionType


class BinanceSpotTradeHistoryAdapter(BaseAdapter):
    REQUIRED_CANONICAL_COLUMNS = ["timestamp", "pair", "side", "price", "quantity"]

    COLUMN_ALIASES: Dict[str, List[str]] = {
        "timestamp": ["Date(UTC)", "Date", "UTC_Time", "Time"],
        "pair": ["Pair", "Symbol"],
        "side": ["Side", "Type"],
        "price": ["Order Price", "Price"],
        "quantity": ["Executed", "Amount", "Quantity"],
        "average_price": ["Average Price"],
        "filled": ["Filled"],
        "value": ["Total"],
        "fee": ["Fee"],
        "fee_coin": ["Fee Coin"],
        "quote_asset": ["Quote Asset"],
        "order_id": ["Order ID"],
        "trade_id": ["Trade ID"],
    }

    KNOWN_QUOTE_ASSETS: Tuple[str, ...] = (
        "BUSD",
        "FDUSD",
        "TUSD",
        "USDT",
        "USDC",
        "BTC",
        "ETH",
        "BNB",
        "EOS",
        "TRX",
        "XRP",
        "GBP",
        "EUR",
        "USD",
    )

    def __init__(self, timezone: Optional[str] = None):
        self.timezone = None
        if timezone:
            try:
                self.timezone = ZoneInfo(timezone)
            except Exception as exc:
                raise ValueError(f"Invalid timezone: {timezone}") from exc

    def _parse_timestamp(self, time_str: str) -> datetime:
        cleaned = time_str.strip()
        try:
            parsed = datetime.fromisoformat(cleaned)
            if parsed.tzinfo is not None:
                return parsed
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%m/%d/%Y %H:%M"):
            try:
                naive = datetime.strptime(cleaned, fmt)
            except ValueError:
                continue
            if self.timezone is not None:
                return naive.replace(tzinfo=self.timezone)
            return naive.replace(tzinfo=ZoneInfo("UTC"))
        raise ValueError(f"Invalid Binance Spot Trade History timestamp: {time_str}")

    def _resolve_column(self, row: Dict[str, Any], canonical: str) -> Optional[str]:
        lowered_row = {str(k).lower(): str(k) for k in row.keys()}
        for alias in self.COLUMN_ALIASES.get(canonical, []):
            lowered_alias = alias.lower()
            if lowered_alias in lowered_row:
                original_key = lowered_row[lowered_alias]
                value = row[original_key]
                if value is not None and str(value).strip() != "":
                    return str(value).strip()
        return None

    def _validate_columns(self, rows: List[Dict[str, Any]]) -> Optional[str]:
        if not rows:
            return "No rows provided."
        for canonical in self.REQUIRED_CANONICAL_COLUMNS:
            if not self._resolve_column(rows[0], canonical):
                return f"Missing required column for {canonical}."
        return None

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

    def _strip_asset_suffix(self, value: str) -> Tuple[str, Optional[str]]:
        match = re.match(r"^([0-9,.]+(?:\.[0-9]+)?)([A-Za-z]+)$", value.strip())
        if match:
            return match.group(1).replace(",", ""), match.group(2)
        return value, None

    def _parse_side(self, side_str: str) -> Side:
        normalized = side_str.strip().upper()
        if normalized == "BUY":
            return Side.BUY
        if normalized == "SELL":
            return Side.SELL
        raise ValueError(f"Invalid Side: {side_str}")

    def _parse_pair(self, pair_str: str) -> Tuple[str, str]:
        pair = pair_str.strip().upper()
        if "/" in pair:
            parts = pair.split("/")
            if len(parts) == 2 and parts[0] and parts[1]:
                return parts[0], parts[1]
            raise ValueError(f"Invalid Pair format: {pair_str}")
        matches = []
        for quote in sorted(self.KNOWN_QUOTE_ASSETS, key=len, reverse=True):
            if pair.endswith(quote) and len(pair) > len(quote):
                matches.append(quote)
        if len(matches) == 1:
            return pair[: -len(matches[0])], matches[0]
        if len(matches) == 0:
            raise ValueError(f"Unable to resolve Pair: {pair_str}")
        raise ValueError(f"Ambiguous Pair: {pair_str} matches multiple quote assets {matches}")

    def _compute_transaction_id(
        self,
        timestamp_str: str,
        pair: str,
        side: str,
        price: str,
        quantity: str,
        fee: Optional[str] = None,
        fee_coin: Optional[str] = None,
        trade_id: Optional[str] = None,
    ) -> str:
        if trade_id:
            raw = f"binance_spot|{trade_id}"
        else:
            raw = f"binance_spot|{timestamp_str}|{pair}|{side}|{price}|{quantity}|{fee or ''}|{fee_coin or ''}"
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
                timestamp_str = self._resolve_column(row, "timestamp")
                pair_str = self._resolve_column(row, "pair")
                side_str = self._resolve_column(row, "side")
                price_str = self._resolve_column(row, "price")
                quantity_str = self._resolve_column(row, "quantity")
                average_price_str = self._resolve_column(row, "average_price")
                filled_str = self._resolve_column(row, "filled")
                value_str = self._resolve_column(row, "value")
                fee_str = self._resolve_column(row, "fee")
                fee_coin_str = self._resolve_column(row, "fee_coin")
                quote_asset_str = self._resolve_column(row, "quote_asset")
                order_id_str = self._resolve_column(row, "order_id")
                trade_id_str = self._resolve_column(row, "trade_id")

                if not timestamp_str:
                    raise ValueError("Missing timestamp.")
                if not pair_str:
                    raise ValueError("Missing pair.")
                if not side_str:
                    raise ValueError("Missing side.")
                if not price_str:
                    raise ValueError("Missing price.")
                if not quantity_str:
                    raise ValueError("Missing quantity.")

                timestamp = self._parse_timestamp(timestamp_str)
                price = self._parse_decimal(price_str, "price")
                side = self._parse_side(side_str)

                quantity_raw = quantity_str
                asset_suffix = None
                quantity_str, asset_suffix = self._strip_asset_suffix(quantity_str)
                if asset_suffix:
                    warnings.append(
                        f"Asset suffix '{asset_suffix}' stripped from quantity for row."
                    )

                quantity = self._parse_decimal(quantity_str, "quantity")

                if quantity <= 0:
                    raise ValueError(f"Quantity must be positive: {quantity}")

                if price <= 0:
                    raise ValueError(f"Price must be positive: {price}")

                try:
                    asset, resolved_quote = self._parse_pair(pair_str)
                except ValueError as exc:
                    warnings.append(str(exc))
                    asset = pair_str
                    resolved_quote = None

                quote_asset = quote_asset_str.upper() if quote_asset_str else resolved_quote
                if not quote_asset and resolved_quote:
                    quote_asset = resolved_quote

                if quote_asset and asset == quote_asset:
                    raise ValueError(f"asset and quote_asset must differ: {asset}")

                fee = None
                fee_asset = None
                if fee_str is not None:
                    fee_value = fee_str.strip()
                    if fee_value:
                        fee_suffix = None
                        if not fee_coin_str:
                            _, fee_suffix = self._strip_asset_suffix(fee_value)
                        if fee_coin_str:
                            fee_asset = fee_coin_str.strip().upper()
                        elif fee_suffix:
                            fee_asset = fee_suffix
                            fee_value = fee_value[: -len(fee_asset)]
                        try:
                            fee = Decimal(fee_value.replace(",", ""))
                        except (InvalidOperation, ValueError) as exc:
                            raise ValueError(f"Invalid fee value: {fee_str}") from exc
                        if fee.is_nan() or fee.is_infinite():
                            raise ValueError(f"Fee is NaN or infinite: {fee_str}")

                value = None
                if value_str is not None and str(value_str).strip():
                    try:
                        value = Decimal(str(value_str).strip().replace(",", ""))
                        if value.is_nan() or value.is_infinite():
                            warnings.append(f"Value is NaN or infinite: {value_str}")
                            value = None
                    except (InvalidOperation, ValueError):
                        warnings.append(f"Invalid value: {value_str}")
                        value = None

                if value is None:
                    try:
                        value = quantity * price
                    except Exception:
                        value = None

                metadata: Dict[str, Any] = {
                    "source": "binance",
                    "source_report_type": "spot_trade_history",
                    "source_pair": pair_str,
                    "source_timestamp": timestamp_str,
                    "source_side": side_str.strip(),
                    "source_price": price_str,
                    "source_quantity": quantity_raw,
                    "source_change_signed": None,
                }
                if average_price_str:
                    metadata["source_average_price"] = average_price_str
                if filled_str:
                    metadata["source_filled"] = filled_str
                if value_str:
                    metadata["source_value"] = str(value_str)
                if fee_str:
                    metadata["source_fee"] = str(fee_str)
                if fee_coin_str:
                    metadata["source_fee_coin"] = fee_coin_str
                if quote_asset_str:
                    metadata["source_quote_asset"] = quote_asset_str
                if order_id_str:
                    metadata["source_order_id"] = order_id_str
                if trade_id_str:
                    metadata["source_trade_id"] = trade_id_str

                tx_id = self._compute_transaction_id(
                    timestamp_str,
                    pair_str,
                    side_str,
                    price_str,
                    quantity_raw,
                    fee_str if fee is not None else None,
                    fee_asset,
                    trade_id_str,
                )

                tx = CanonicalTransaction(
                    transaction_id=tx_id,
                    source=Source.BINANCE,
                    source_transaction_id=trade_id_str,
                    timestamp=timestamp,
                    transaction_type=TransactionType.TRADE,
                    side=side,
                    asset=asset,
                    quantity=quantity,
                    quote_asset=quote_asset,
                    price=price,
                    value=value,
                    fee=fee,
                    fee_asset=fee_asset,
                    confidence=1.0,
                    metadata=metadata,
                )
                transactions.append(tx)
            except Exception as exc:
                errors.append(f"Failed to adapt Spot Trade History row: {exc}")

        return AdapterResult(transactions=transactions, warnings=warnings, errors=errors)
