# CryptoClean

CryptoClean is a cryptocurrency tax and portfolio tool. Milestone 001 provides CSV ingestion with basic exchange detection.

## Current Milestone

Milestone 010: Binance Spot Trade History adapter, source/report-type detection, canonical TRADE mapping, and pipeline integration. P&L and tax calculation are NOT yet implemented.

## Getting Started

### Activate Virtual Environment

```powershell
.\.venv\Scripts\Activate.ps1
```

### Install Dependencies

```powershell
pip install -r requirements.txt
```

### Start FastAPI Server

```powershell
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Or run directly:

```powershell
python backend/main.py
```

### Run Tests

```powershell
pytest
```

## Available Endpoints

- `GET /health` - Health check
- `POST /api/v1/ingest` - Upload a CSV file for ingestion, exchange detection, and report-type classification
- `POST /api/v1/process` - Upload a CSV file for full pipeline processing (adapter + reconciliation + comments)

## Supported Sources and Report Types

CryptoClean distinguishes between different report types from the same exchange.

| Exchange | Report Type | Description |
|----------|-------------|-------------|
| Binance | `transaction_record` | User ID, Time, Account, Operation, Coin, Change, Remark |
| Binance | `spot_trade_history` | Date(UTC), Pair/Symbol, Side/Type, Order Price/Price, Amount/Quantity, Fee, Fee Coin |

Source detection is performed by a single detector that scores filename keywords and column patterns. The detector returns both the exchange ID and the report type.

## Canonical Transaction Model

CryptoClean uses a single internal representation for all transactions, regardless of source.

```
External source (exchange CSV, blockchain data, manual entry)
        |
        v
Exchange / wallet adapter (source + report type specific)
        |
        v
Canonical Transaction model
        |
        v
Downstream engines (P&L, tax, reconciliation)
```

The canonical model is exchange-independent, strongly typed, and uses `Decimal` for all financial quantities to preserve precision. BUY/SELL belongs in the `Side` field; the `TransactionType` field classifies the economic event (TRADE, DEPOSIT, WITHDRAWAL, TRANSFER, FEE, REWARD, UNKNOWN, etc.).

## Binance Spot Trade History Adapter

The Binance Spot Trade History adapter converts Binance Spot Trade History CSV exports into `CanonicalTransaction` objects with `TransactionType.TRADE`.

### Supported Format

The adapter supports the Binance Spot Trade History export format with the following columns:

- `Date(UTC)` — trade timestamp (required)
- `Pair` or `Symbol` — trading pair symbol (required)
- `Side` or `Type` — BUY or SELL (required)
- `Order Price` or `Price` — execution price (required)
- `Amount`, `Executed`, or `Quantity` — base asset quantity (required)
- `Average Price` — optional average price
- `Filled` — optional filled quantity
- `Total` — optional quote asset value
- `Fee` — optional fee amount
- `Fee Coin` — optional fee asset
- `Quote Asset` — optional explicit quote asset override
- `Order ID` — optional order identifier
- `Trade ID` — optional trade identifier

Column mapping is explicit and configurable. If the exact export format varies, the mapping can be updated without changing the adapter logic.

### Canonical Mapping

| Source Field | Canonical Field | Notes |
|--------------|-----------------|-------|
| `Date(UTC)` | `timestamp` | Timezone-aware; explicit timezone required |
| `Pair` / `Symbol` | `asset`, `quote_asset` | Split by `/` or resolved from known quote assets |
| `Side` / `Type` | `side` | `Side.BUY` or `Side.SELL` |
| `Order Price` / `Price` | `price` | `Decimal` |
| `Amount` / `Executed` / `Quantity` | `quantity` | `Decimal`; positive for both BUY and SELL |
| `Total` | `value` | `Decimal`; quote asset value |
| `Fee` | `fee` | `Decimal` |
| `Fee Coin` | `fee_asset` | Preserved as-is; not converted |
| `Trade ID` | `source_transaction_id` | If present |
| `Order ID` | `metadata.source_order_id` | If present |

### Symbol Resolution

The adapter preserves the original Binance symbol. Where reliably possible, it derives `asset` and `quote_asset`:

- Pairs containing `/` are split directly (e.g., `BTC/USDT` → `BTC`, `USDT`).
- Pairs without `/` are resolved against a known quote-asset list: `BUSD`, `FDUSD`, `TUSD`, `USDT`, `USDC`, `BTC`, `ETH`, `BNB`, `EOS`, `TRX`, `XRP`, `GBP`, `EUR`, `USD`.
- If the pair cannot be resolved confidently (unknown symbol or ambiguous match), the raw symbol is preserved in `asset` and `quote_asset` is set to `None`. A warning is emitted.

### Decimal Strategy

All financial fields (`quantity`, `price`, `value`, `fee`) are parsed as `Decimal` from their string representations. The pipeline converts all CSV cell values to strings before passing them to the adapter, ensuring pandas float inference does not alter precision. Invalid, `NaN`, or infinite values are rejected with errors or warnings.

### Timestamp Strategy

The adapter requires an explicit timezone for naive Binance timestamps. Supported formats include `%Y-%m-%d %H:%M:%S` and ISO 8601 variants. The resulting `timestamp` is timezone-aware.

### Fee Handling

Fees are preserved exactly as provided. The adapter stores both `fee` (amount) and `fee_asset` (asset). Fees are never converted to a common currency or used to calculate P&L. For example, a BNB fee on a BTC/USDT trade remains `fee_asset = BNB`.

### Deterministic Transaction ID

The same Spot Trade History row imported twice produces the same `transaction_id`.

- If a `Trade ID` is present, the ID is derived from `binance_spot|{trade_id}`.
- If no `Trade ID` is present, the ID is derived from a deterministic hash of stable source fields: timestamp, pair, side, price, quantity, fee, and fee coin.
- User ID is never included in deterministic IDs.

### Privacy

The adapter never stores or returns User IDs, API keys, secrets, passwords, private keys, or seed phrases. Only the explicitly mapped source fields are preserved in metadata.

## Processing Pipeline

The pipeline orchestrates ingestion, detection, adaptation, reconciliation, and comment preservation.

```
CSV
  -> safe ingestion (reader)
  -> source + report-type detection (detector)
  -> adapter selection (source + report type)
  -> CanonicalTransaction[]
  -> duplicate detection (M004)
  -> transfer reconciliation (M005)
  -> convert reconciliation (M007)
  -> comment preservation (M009)
  -> ProcessingResult
```

Pipeline order is fixed: validate/read input, detect source and report type, select adapter, adapt rows, run duplicate detection, then transfer reconciliation, then convert reconciliation, then comment preservation. Timezone must be supplied explicitly to the pipeline (no silent UTC default). The pipeline never deletes transactions; duplicate, transfer, convert, and comment findings are attached separately to the `ProcessingResult` for auditability. No P&L or tax calculation is performed.

## Duplicate Detection Engine

CryptoClean includes a standalone duplicate-detection engine that operates on `CanonicalTransaction` objects.

```
Canonical transactions
        |
        v
DuplicateDetector (fingerprint + scoring + grouping)
        |
        v
DuplicateResult (groups / candidates / unique ids)
```

The engine classifies pairs/groups as `EXACT_DUPLICATE`, `PROBABLE_DUPLICATE`, `POSSIBLE_DUPLICATE`, or `UNIQUE` using deterministic rules and never deletes transactions. Cross-source duplicates are not inferred without a strong blockchain identifier (`tx_hash`). Internal transfer legs are not treated as duplicates.

## Transfer Reconciliation Engine

CryptoClean includes a reconciliation engine that links the two legs of an internal transfer (for example Spot ↔ Futures) into a single `INTERNAL_TRANSFER`.

```
Canonical transactions
        |
        v
TransferReconciler (leg extraction + compatibility + direction)
        |
        v
TransferResult (matches / unmatched legs)
```

The engine requires both legs to be `TRANSFER`, share asset, share absolute quantity, have opposite signed changes, fall within a configurable timestamp tolerance, and represent compatible internal accounts. Source-specific semantics (e.g., Binance account/operation mappings) live in a separate rule layer so the generic engine stays exchange-independent. Matched transfers keep both original source transactions intact.

## Convert Reconciliation

CryptoClean includes a dedicated Binance Convert reconciliation engine that reconstructs economic conversion events from the Transaction Record export.

```
CanonicalTransaction[]
        |
        v
ConvertReconciler (generic) + BinanceConvertRules (source-specific)
        |
        v
ConvertResult (matches / unresolved legs)
```

A Convert finding requires at least one negative leg (asset leaving the account) and at least one positive leg (asset entering the account), different assets, same source/account, same operation ("Binance Convert"), and timestamps within a configurable tolerance. Direction is derived from the signed change, never from row ordering. Ambiguous candidate pairings are left unresolved with a warning rather than guessed. Original transactions are preserved.

## Comment Preservation

CryptoClean includes a generic comment engine that extracts and preserves source remarks/comments from canonical transactions. Binance-specific rules ensure raw remarks are preserved unchanged. User ID placeholders are excluded from comment output.

## Notes

- No frontend, database, authentication, payments, P&L, classification, or blockchain integrations in this milestone.
- P&L is NOT yet calculated. Spot Trade History provides the input for future cost-basis reconstruction.
- Do not upload files containing API keys, passwords, exchange credentials, private keys, or seed phrases.
