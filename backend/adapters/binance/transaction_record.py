from __future__ import annotations

import hashlib
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from zoneinfo import ZoneInfo

from backend.adapters.base import BaseAdapter, AdapterResult
from backend.models.transaction import CanonicalTransaction, Side, Source, TransactionType


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

    def _map_operation(self, operation: str, change: Optional[str] = None) -> tuple[TransactionType, Optional[Side], str]:
        op = operation.strip()
        signed = Decimal("0")
        if change is not None:
            try:
                signed = Decimal(change.strip())
            except (InvalidOperation, ValueError):
                signed = Decimal("0")

        if op == "Deposit":
            return TransactionType.DEPOSIT, None, ""

        if op == "Withdraw":
            return TransactionType.WITHDRAWAL, None, ""

        if op in {"Transaction Buy", "Auto-Invest Transaction"}:
            if signed > 0:
                return TransactionType.TRADE, Side.BUY, ""
            return TransactionType.UNKNOWN, None, f"Non-positive {op}."

        if op in {"Transaction Sold", "Transaction Spend", "Merchant Acquiring"}:
            if signed < 0:
                return TransactionType.TRADE, Side.SELL, ""
            return TransactionType.UNKNOWN, None, f"Non-negative {op}."

        if op == "Transaction Revenue":
            if signed > 0:
                return TransactionType.TRADE, Side.BUY, ""
            return TransactionType.UNKNOWN, None, f"Non-negative {op}."

        if op == "Buy":
            return TransactionType.TRADE, Side.BUY, ""

        if op == "Sell":
            return TransactionType.TRADE, Side.SELL, ""

        if op in {
            "Binance Convert",
            "Futures Convert - From",
            "Futures Convert - To",
            "Stablecoins Auto-Conversion",
            "Token Swap - Redenomination/Rebranding",
            "Small Assets Exchange BNB",
            "Small Assets Exchange",
        }:
            return TransactionType.UNKNOWN, None, f"{op} rows should be grouped later."

        if op in {
            "Transfer Between Spot and UM Futures",
            "Transfer Between UM Futures and Funding",
            "Transfer Between Spot and Funding",
            "Transfer Between Spot and CM Futures",
            "Transfer Between CM Futures and Funding",
            "Transfer Between Spot and Margin",
            "Transfer Between Margin and Funding",
            "Transfer Between Spot and Isolated Margin",
            "Transfer",
        }:
            return TransactionType.TRANSFER, None, ""

        if op == "Fee":
            return TransactionType.FEE, None, ""

        if op == "Transaction Fee":
            return TransactionType.FEE, None, ""

        if op == "Funding Fee":
            return TransactionType.FEE, None, "Funding Fee preserved in metadata."

        if op == "Realized Profit and Loss":
            if signed > 0:
                return TransactionType.REWARD, None, "Realized profit mapped to REWARD."
            if signed < 0:
                return TransactionType.FEE, None, "Realized loss mapped to FEE."
            return TransactionType.UNKNOWN, None, "Zero-change Realized P&L."

        if op == "P2P Trading":
            if signed > 0:
                return TransactionType.TRADE, Side.BUY, "P2P buy inferred from positive change."
            if signed < 0:
                return TransactionType.TRADE, Side.SELL, "P2P sell inferred from negative change."
            return TransactionType.UNKNOWN, None, "Zero-change P2P trade."

        if op == "Crypto Box":
            return TransactionType.REWARD, None, ""

        if op == "Crypto Box Refund":
            return TransactionType.REWARD, None, ""

        if op == "Asset Recovery":
            return TransactionType.DEPOSIT, None, ""

        if op == "Simple Earn Flexible Subscription":
            return TransactionType.TRANSFER, None, ""

        if op == "Simple Earn Flexible Redemption":
            return TransactionType.TRANSFER, None, ""

        if op == "Simple Earn Flexible Airdrop":
            return TransactionType.AIRDROP, None, ""

        if op == "Simple Earn Flexible Interest":
            return TransactionType.REWARD, None, ""

        if op in {"Simple Earn Locked Subscription", "Simple Earn Locked Redemption"}:
            return TransactionType.TRANSFER, None, ""

        if op == "Staking Purchase":
            return TransactionType.TRANSFER, None, ""

        if op == "Staking Redemption":
            return TransactionType.TRANSFER, None, ""

        if op == "Staking Rewards":
            return TransactionType.REWARD, None, ""

        if op == "Launchpool":
            return TransactionType.REWARD, None, ""

        if op == "Launchpool Airdrop - User Claim Distribution":
            return TransactionType.AIRDROP, None, ""

        if op == "Launchpool Subscription/Redemption":
            return TransactionType.TRANSFER, None, ""

        if op == "Distribution":
            return TransactionType.AIRDROP, None, ""

        if op in {"Airdrop Assets", "Airdrop"}:
            return TransactionType.AIRDROP, None, ""

        if op in {
            "Cash Voucher",
            "Cash Voucher Distribution",
            "Commission Rebate",
            "Referrer Commission",
            "Insurance Fund Refund",
            "Transaction Revenue",
        }:
            return TransactionType.REWARD, None, ""

        if op == "Commission Fee":
            return TransactionType.FEE, None, ""

        if op == "NFT - Unfreeze for Payment":
            return TransactionType.WITHDRAWAL, None, ""

        return TransactionType.UNKNOWN, None, f"Unrecognized Binance operation: {op}"

    def _pair_transaction_legs(self, transactions: List[CanonicalTransaction]) -> None:
        from collections import defaultdict
        from decimal import Decimal

        groups = defaultdict(list)
        for tx in transactions:
            if tx.transaction_type == TransactionType.TRADE and tx.timestamp:
                groups[tx.timestamp].append(tx)

        for timestamp, txs in groups.items():
            if len(txs) < 2:
                continue

            trade_ops = []
            for tx in txs:
                op = (tx.metadata or {}).get("source_operation", "")
                if op in {"Transaction Buy", "Transaction Spend", "Transaction Sold", "Transaction Revenue"}:
                    trade_ops.append(tx)

            if len(trade_ops) != 2:
                continue

            buy_leg = next((tx for tx in trade_ops if (tx.metadata or {}).get("source_operation") == "Transaction Buy"), None)
            spend_leg = next((tx for tx in trade_ops if (tx.metadata or {}).get("source_operation") == "Transaction Spend"), None)
            sold_leg = next((tx for tx in trade_ops if (tx.metadata or {}).get("source_operation") == "Transaction Sold"), None)
            revenue_leg = next((tx for tx in trade_ops if (tx.metadata or {}).get("source_operation") == "Transaction Revenue"), None)

            pair = None
            acquisition_leg = None
            disposal_leg = None
            if buy_leg and spend_leg and buy_leg.asset != spend_leg.asset:
                acquisition_leg = buy_leg
                disposal_leg = spend_leg
                pair = (acquisition_leg, disposal_leg)
            elif sold_leg and revenue_leg and sold_leg.asset != revenue_leg.asset:
                acquisition_leg = revenue_leg
                disposal_leg = sold_leg
                pair = (acquisition_leg, disposal_leg)

            if not pair:
                continue

            acquisition_qty = acquisition_leg.quantity
            disposal_qty = disposal_leg.quantity
            if acquisition_qty <= 0 or disposal_qty <= 0:
                continue

            if buy_leg and spend_leg and buy_leg.asset != spend_leg.asset:
                implied_price = disposal_qty / acquisition_qty
                implied_value = disposal_qty
            elif sold_leg and revenue_leg and sold_leg.asset != revenue_leg.asset:
                implied_price = acquisition_qty / disposal_qty
                implied_value = acquisition_qty
            else:
                continue

            if acquisition_leg.price is None:
                acquisition_leg.__dict__["price"] = implied_price
            if acquisition_leg.value is None:
                acquisition_leg.__dict__["value"] = implied_value
            if disposal_leg.price is None:
                disposal_leg.__dict__["price"] = implied_price
            if disposal_leg.value is None:
                disposal_leg.__dict__["value"] = implied_value

            if acquisition_leg.quote_asset is None:
                if buy_leg and spend_leg and buy_leg.asset != spend_leg.asset:
                    acquisition_leg.__dict__["quote_asset"] = spend_leg.asset
                    disposal_leg.__dict__["quote_asset"] = buy_leg.asset
                elif sold_leg and revenue_leg and sold_leg.asset != revenue_leg.asset:
                    acquisition_leg.__dict__["quote_asset"] = sold_leg.asset
                    disposal_leg.__dict__["quote_asset"] = revenue_leg.asset

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

                tx_type, side, op_warning = self._map_operation(operation, change_str)
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

        self._pair_transaction_legs(transactions)

        return AdapterResult(transactions=transactions, warnings=warnings, errors=errors)
