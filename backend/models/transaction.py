from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Source(str, Enum):
    BINANCE = "binance"
    COINBASE = "coinbase"
    BYBIT = "bybit"
    ETHEREUM = "ethereum"
    SOLANA = "solana"
    MANUAL = "manual"
    UNKNOWN = "unknown"


class TransactionType(str, Enum):
    TRADE = "TRADE"
    SWAP = "SWAP"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSFER = "TRANSFER"
    FEE = "FEE"
    REWARD = "REWARD"
    STAKING = "STAKING"
    AIRDROP = "AIRDROP"
    UNKNOWN = "UNKNOWN"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class CanonicalTransaction(BaseModel):
    model_config = ConfigDict(frozen=True)

    transaction_id: str
    source: Source
    source_transaction_id: Optional[str] = None

    timestamp: datetime

    transaction_type: TransactionType
    side: Optional[Side] = None

    asset: str
    quantity: Decimal

    quote_asset: Optional[str] = None
    price: Optional[Decimal] = None
    value: Optional[Decimal] = None

    fee: Optional[Decimal] = None
    fee_asset: Optional[str] = None
    fee_value: Optional[Decimal] = None

    wallet: Optional[str] = None
    counterparty: Optional[str] = None
    tx_hash: Optional[str] = None

    confidence: float = Field(ge=0.0, le=1.0)
    notes: Optional[str] = None

    metadata: Optional[Dict[str, Any]] = None

    @field_validator("asset")
    @classmethod
    def asset_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("asset cannot be blank.")
        return v.strip()

    @field_validator("transaction_id")
    @classmethod
    def transaction_id_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("transaction_id cannot be blank.")
        return v.strip()

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware.")
        return v

    @field_validator("quantity", "price", "value", "fee", "fee_value", mode="before")
    @classmethod
    def decimal_not_nan_or_inf(cls, v: Any) -> Any:
        if v is None:
            return v
        if isinstance(v, Decimal):
            if v.is_nan() or v.is_infinite():
                raise ValueError("Decimal value must not be NaN or infinite.")
            return v
        try:
            d = Decimal(str(v))
        except (InvalidOperation, ValueError) as e:
            raise ValueError("Invalid Decimal value.") from e
        if d.is_nan() or d.is_infinite():
            raise ValueError("Decimal value must not be NaN or infinite.")
        return d

    @model_validator(mode="after")
    def validate_trade_side(self) -> CanonicalTransaction:
        if self.transaction_type == TransactionType.TRADE and self.side is None:
            raise ValueError("side is required for TRADE transactions.")
        if self.side is not None and self.transaction_type != TransactionType.TRADE:
            raise ValueError("side is only valid for TRADE transactions.")
        return self

    @field_validator("metadata")
    @classmethod
    def metadata_no_secrets(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if v is None:
            return v
        sensitive_patterns = [
            "api key",
            "apikey",
            "api_key",
            "api_secret",
            "api secret",
            "private key",
            "privatekey",
            "private_key",
            "seed phrase",
            "seedphrase",
            "password",
            "passphrase",
            "secret",
        ]
        for key in v:
            key_lower = str(key).lower()
            for pattern in sensitive_patterns:
                if pattern in key_lower:
                    raise ValueError(f"Metadata contains a sensitive key: {key}")
        return v

    @field_validator("fee", "fee_value")
    @classmethod
    def fee_non_negative(cls, v: Any) -> Any:
        if v is None:
            return v
        if isinstance(v, Decimal) and v < 0:
            raise ValueError("fee must not be negative.")
        return v

    @field_validator("quantity")
    @classmethod
    def quantity_positive(cls, v: Any) -> Any:
        if v is None:
            return v
        if isinstance(v, Decimal) and v <= 0:
            raise ValueError("quantity must be positive.")
        return v
