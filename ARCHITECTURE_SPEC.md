# CryptoClean Architecture Specification

> **Status**: Current as of M030 production deployment (379 tests passed, 0 failed).
> **Generated**: M014 recovery effort. Updated through M030.
> **Canonical source of truth**: This document supersedes `M010_ARCHITECTURE_AUDIT.txt` for architecture decisions. The M010 file remains on disk for historical reference but is known to contain NUL-byte corruption and should not be treated as authoritative.

---

## 1. Original M010 Requirements (Recovered)

The original M010 audit text is partially recoverable from `M010_ARCHITECTURE_AUDIT.txt` by stripping NUL bytes, but the file is not considered a clean artifact. Recovered intent:

- Provide a Binance Spot Trade History adapter.
- Map Spot Trade History rows to the existing canonical `CanonicalTransaction` model.
- Use `TransactionType.TRADE` for Spot Trade History rows.
- Represent BUY/SELL through `Side.BUY` / `Side.SELL`.
- Integrate Spot Trade History into the existing processing pipeline.
- Preserve the single canonical model across all sources.
- Use `Decimal` for all financial quantities.
- Do not implement P&L or tax calculation in M010.

**Note**: The original M010 document also embedded full source-code dumps of most backend modules. Those dumps are corrupted by NUL bytes. The code on disk is the authoritative implementation.

---

## 2. Current Implementation

### 2.1 Models

**File**: `backend/models/transaction.py`

`CanonicalTransaction` is the single internal representation for all transactions, regardless of source.

Key fields:

| Field | Type | Purpose |
|---|---|---|
| `transaction_id` | `str` | Deterministic identity for the transaction |
| `source` | `Source` enum | Exchange / origin system |
| `source_transaction_id` | `Optional[str]` | Exchange-native identifier (e.g., Binance Trade ID) |
| `timestamp` | `datetime` | Timezone-aware event time |
| `transaction_type` | `TransactionType` enum | Economic event classification |
| `side` | `Optional[Side]` | BUY or SELL; only valid for TRADE |
| `asset` | `str` | Primary asset |
| `quantity` | `Decimal` | Absolute quantity of `asset` |
| `quote_asset` | `Optional[str]` | Quote asset for pricing |
| `price` | `Optional[Decimal]` | Unit price in `quote_asset` |
| `value` | `Optional[Decimal]` | Total value in `quote_asset` |
| `fee` | `Optional[Decimal]` | Fee amount |
| `fee_asset` | `Optional[str]` | Asset in which fee was paid |
| `fee_value` | `Optional[Decimal]` | Fee value in quote asset |
| `wallet` | `Optional[str]` | Wallet identifier |
| `counterparty` | `Optional[str]` | Counterparty identifier |
| `tx_hash` | `Optional[str]` | Blockchain transaction hash |
| `confidence` | `float` | Detection confidence [0.0, 1.0] |
| `notes` | `Optional[str]` | Free-text annotations |
| `metadata` | `Optional[Dict[str, Any]]` | Source-specific raw fields |

**Enums**:

- `Source`: BINANCE, COINBASE, BYBIT, ETHEREUM, SOLANA, MANUAL, UNKNOWN
- `TransactionType`: TRADE, SWAP, DEPOSIT, WITHDRAWAL, TRANSFER, FEE, REWARD, STAKING, AIRDROP, UNKNOWN
- `Side`: BUY, SELL

**Invariants enforced by model validators**:

- `transaction_id` must be non-blank.
- `timestamp` must be timezone-aware.
- `quantity`, `price`, `value`, `fee`, `fee_value` must be valid `Decimal` (no NaN, no infinite).
- `side` is required for `TRADE`; `side` is forbidden for non-`TRADE`.
- `metadata` keys must not match sensitive patterns (API keys, secrets, passwords, etc.).

`ProcessingResult` and `ProcessingSummary` are defined in `backend/processing/models.py`. `ProcessingResult` accumulates transactions, warnings, errors, and reconciliation findings. `ProcessingSummary` provides counts by transaction type and reconciliation category.

### 2.2 Ingestion

**File**: `backend/ingestion/reader.py`

`read_csv_safely` reads a CSV file into a `pandas.DataFrame`. It normalizes column names and returns the DataFrame, row count, column count, column names, and any warnings. Empty values are left as NaN for downstream handling.

**File**: `backend/ingestion/detector.py`

`detect_exchange` examines the filename and DataFrame columns to determine:

- `exchange` (e.g., `"binance"`)
- `report_type` (e.g., `"transaction_record"`, `"spot_trade_history"`)
- `confidence`
- `indicators`
- `warnings`

If the source cannot be determined, `exchange` is `"unknown"` and processing halts with an error.

### 2.3 Adapters

**Base**: `backend/adapters/base.py`

`BaseAdapter` defines the interface. `AdapterResult` carries `transactions`, `warnings`, and `errors`.

**Binance Transaction Record**: `backend/adapters/binance/transaction_record.py`

`BinanceTransactionRecordAdapter` converts Binance Transaction Record CSV exports into `CanonicalTransaction` objects.

- Required columns: `User ID`, `Time`, `Account`, `Operation`, `Coin`, `Change`, `Remark`
- Maps operations to `TransactionType` (e.g., `Deposit` → `DEPOSIT`, `Transfer Between Spot and UM Futures` → `TRANSFER`, `Binance Convert` → `UNKNOWN`, `Fee` → `FEE`, etc.)
- Produces `source_change_signed` in metadata for transfer/convert reconciliation legs.
- Deterministic `transaction_id` based on account, time, operation, coin, change, and remark.
- User IDs are never included in transaction identity.

**Binance Spot Trade History**: `backend/adapters/binance/spot_trade_history.py`

`BinanceSpotTradeHistoryAdapter` converts Binance Spot Trade History CSV exports into `CanonicalTransaction` objects with `TransactionType.TRADE`.

- Supported columns (with aliases): `Date(UTC)`, `Pair`/`Symbol`, `Side`/`Type`, `Order Price`/`Price`, `Amount`/`Executed`/`Quantity`, `Average Price`, `Filled`, `Total`, `Fee`, `Fee Coin`, `Quote Asset`, `Order ID`, `Trade ID`
- Side is parsed from `Side` or `Type` column; only `BUY` and `SELL` are valid.
- Pair is resolved by splitting on `/` or by matching known quote-asset suffixes.
- Quantity and price must be positive `Decimal` values.
- Fee is parsed as `Decimal`; invalid fees cause row-level rejection.
- `asset == quote_asset` is rejected.
- Deterministic `transaction_id`: prefers `Trade ID` when available; otherwise hashes timestamp, pair, side, price, quantity, fee, and fee coin.
- `source_change_signed` is explicitly set to `None` in metadata.

### 2.4 Processing

**File**: `backend/processing/pipeline.py`

`ProcessingPipeline` orchestrates the full flow:

1. Read CSV (`read_csv_safely`)
2. Detect exchange and report type (`detect_exchange`)
3. Resolve adapter via `AdapterRegistry`
4. Adapt rows to canonical transactions
5. Run `DuplicateDetector`
6. Run `TransferReconciler`
7. Run `ConvertReconciler`
8. Run `CommentEngine`
9. Build `ProcessingSummary`

Adapter selection is performed by `AdapterRegistry` (`backend/adapters/registry.py`), which maps `(source, report_type)` tuples to adapter classes. The pipeline no longer contains exchange-specific branching logic. Unsupported `(source, report_type)` combinations raise `AdapterNotFoundError`.

`process_csv_content` accepts raw CSV text, writes it to a temporary file, and delegates to `process_file`.

### 2.5 Reconciliation

#### DuplicateDetector

**File**: `backend/reconciliation/duplicates.py`

`DuplicateDetector` identifies duplicate transactions using weighted field scoring.

- Buckets transactions by `transaction_id`, `(source, source_transaction_id)`, `tx_hash`, and `(source, asset, quantity)`.
- Scores pairs using deterministic weights (e.g., identical `transaction_id` = 100, same `source_transaction_id` = 70, same `tx_hash` = 70, same `asset` = 16, etc.).
- Thresholds: `EXACT_DUPLICATE` ≥ 100, `PROBABLE_DUPLICATE` ≥ 90, `POSSIBLE_DUPLICATE` ≥ 70.
- Transfer pairs without a strong identifier are conservatively excluded from duplicate consideration.
- Uses union-find to group transactions.

#### TransferReconciler

**File**: `backend/reconciliation/transfers.py`

`TransferReconciler` matches transfer legs using exchange-specific rules.

- Only `TransactionType.TRANSFER` transactions are eligible.
- Legs are extracted by `TransferRules` implementations (e.g., `BinanceTransferRules`).
- Matches require: same asset, equal absolute quantity, opposite signed amounts, same source, compatible accounts, and timestamps within tolerance.
- Returns `TransferResult` with `matches` and `unmatched_leg_ids`.

**File**: `backend/reconciliation/binance_transfers.py`

`BinanceTransferRules` extracts transfer legs from Binance Transaction Record transactions.

- Only processes `TransactionType.TRANSFER`.
- Requires `source_change_signed` in metadata.
- Recognized operations: `Transfer Between Spot and UM Futures`, `Transfer Between UM Futures and Funding`, `Transfer Between Spot and Funding`.

#### ConvertReconciler

**File**: `backend/reconciliation/converts.py`

`ConvertReconciler` matches Binance Convert legs.

- Only `TransactionType.UNKNOWN` transactions with `source_operation == "Binance Convert"` are eligible (enforced by `BinanceConvertRules`).
- Groups legs by `(source, account)`.
- Requires exactly one negative and one positive leg, different assets, and timestamps within tolerance.
- Returns `ConvertResult` with `matches`, `unresolved_leg_ids`, and `warnings`.

**File**: `backend/reconciliation/binance_converts.py`

`BinanceConvertRules` extracts convert legs from Binance Transaction Record transactions.

- Only processes `TransactionType.UNKNOWN`.
- Requires `source_operation == "Binance Convert"` and `source_change_signed` in metadata.
- Zero signed amounts are excluded.

### 2.6 CommentEngine

**File**: `backend/processing/comments.py`

`CommentEngine` preserves raw remarks from source transactions.

- Iterates transactions and reads `source_remark` from metadata.
- For Binance source, skips remarks that are user IDs (`"REDACTED"`, `"USER ID"`, `"USERID"`).
- Preserves the raw remark text by default.
- Returns `CommentResult` with a list of `CommentFinding` objects.

### 2.7 API

**File**: `backend/main.py`

- `GET /health` — returns service health status with version.
- `POST /api/v1/ingest` — uploads a CSV, performs exchange detection and report-type classification, returns detection result.
- `POST /api/v1/process` — uploads a CSV, runs the full processing pipeline (adapter + reconciliation + comments), returns `ProcessingResult` as JSON.
- `POST /api/v1/account` — uploads a CSV, runs the full processing pipeline with accounting enabled, returns `ProcessingResult` with accounting results.

All endpoints accept `multipart/form-data` file uploads. The `/api/v1/process` and `/api/v1/account` endpoints require a `timezone` query parameter.

**CORS Configuration:**

CORS middleware is configured with configurable origins via the `CORS_ORIGINS` environment variable (comma-separated). Default is `*` (all origins).

**Security Headers:**

All responses include security headers:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Cache-Control: no-store`

**`/api/v1/process` status semantics:**

- `200 OK` — all rows adapted successfully; `result.errors` is empty.
- `207 Multi-Status` — some rows failed adaptation but at least one transaction was produced. The response body is the full `ProcessingResult` JSON including `errors` and `transactions`.
- `400 Bad Request` — complete failure (no transactions produced) due to missing timezone, invalid content type, unsupported exchange/report type, malformed CSV, or all rows failing adaptation.
- `500 Internal Server Error` — unexpected server error. No internal details are exposed in the response body.

---

## 3. Architectural Decisions Made After M010

### 3.1 Spot Trade Representation

A Binance Spot Trade History row maps to `TransactionType.TRADE` with `Side.BUY` or `Side.SELL`. Quantity is always positive. BUY/SELL semantics are captured in `side`; `transaction_type` classifies the economic event.

### 3.2 Spot Trade Reconciliation Boundary

Normal Spot Trade History trades are **not** transfer legs and **not** convert legs.

- `TransferReconciler` only matches `TransactionType.TRANSFER` transactions (`backend/reconciliation/transfers.py:88-93`).
- `BinanceTransferRules.extract_leg` returns `None` for non-`TRANSFER` transactions (`backend/reconciliation/binance_transfers.py:21-23`).
- `ConvertReconciler` only matches `TransactionType.UNKNOWN` transactions with `source_operation == "Binance Convert"` (`backend/reconciliation/binance_converts.py:14-19`).

`source_change_signed` is **not** used to represent a Spot Trade as a single reconciliation leg.

### 3.3 Financial Data Integrity

- All financial fields use `Decimal`.
- Invalid financial values are rejected at row level (e.g., invalid fee, NaN, infinite).
- `asset == quote_asset` is rejected to prevent nonsensical self-pairs.
- Malformed fee values cause row-level rejection, not silent zeroing.

### 3.4 Deterministic Identity

- Same source row must produce the same `transaction_id`.
- Trade ID is preferred where available (`binance_spot|{trade_id}`).
- User IDs are never included in transaction identity.

### 3.5 Privacy

- `metadata` keys are validated against sensitive patterns.
- User IDs from source data are stripped from remarks by `CommentEngine`.
- No API keys, passwords, private keys, or seed phrases are accepted or retained.

### 3.6 Pipeline Order

The processing sequence is:

1. CSV ingestion (`read_csv_safely`)
2. Source / report-type detection (`detect_exchange`)
3. Adapter selection and canonical adaptation
4. Duplicate detection (`DuplicateDetector`)
5. Transfer reconciliation (`TransferReconciler`)
6. Convert reconciliation (`ConvertReconciler`)
7. Comment processing (`CommentEngine`)
8. Summary building (`_build_summary`)

### 3.7 No Transaction Deletion

Reconciliation identifies relationships and findings but does not delete source transactions. All adapted transactions remain in `ProcessingResult.transactions`.

---

## 4. Component Reference

### 4.1 Models

| Component | File | Responsibility |
|---|---|---|
| `CanonicalTransaction` | `backend/models/transaction.py` | Single internal representation for all transactions |
| `Source` enum | `backend/models/transaction.py` | Exchange / origin system identifier |
| `TransactionType` enum | `backend/models/transaction.py` | Economic event classification |
| `Side` enum | `backend/models/transaction.py` | BUY / SELL direction for trades |
| `ProcessingResult` | `backend/processing/models.py` | Aggregated pipeline output |
| `ProcessingSummary` | `backend/processing/models.py` | Counts by type and reconciliation category |

### 4.2 Ingestion

| Component | File | Responsibility |
|---|---|---|
| `read_csv_safely` | `backend/ingestion/reader.py` | Read CSV into DataFrame with normalization |
| `detect_exchange` | `backend/ingestion/detector.py` | Identify exchange and report type from filename and columns |

### 4.3 Adapters

| Component | File | Responsibility |
|---|---|---|
| `BaseAdapter` | `backend/adapters/base.py` | Abstract adapter interface |
| `BinanceTransactionRecordAdapter` | `backend/adapters/binance/transaction_record.py` | Convert Binance Transaction Record to canonical |
| `BinanceSpotTradeHistoryAdapter` | `backend/adapters/binance/spot_trade_history.py` | Convert Binance Spot Trade History to canonical TRADE |
| `CoinbaseTransactionRecordAdapter` | `backend/adapters/coinbase/transaction_record.py` | Convert Coinbase Transaction Record to canonical |

**Coinbase Transaction Record format contract:**

- **Source**: `coinbase`
- **Report type**: `transaction_record`
- **Required columns**: `Timestamp`, `Transaction Type`, `Asset`, `Quantity Transacted`
- **Optional columns**: `Spot Price Currency`, `Spot Price at Transaction`, `Subtotal`, `Total (inclusive of fees)`, `Fees`, `Notes`
- **Transaction type mappings**:
  - `Buy` → `TransactionType.TRADE`, `Side.BUY`
  - `Sell` → `TransactionType.TRADE`, `Side.SELL`
  - `Send` → `TransactionType.WITHDRAWAL`
  - `Receive` → `TransactionType.DEPOSIT`
  - `Convert` → `TransactionType.SWAP`
  - Other → `TransactionType.UNKNOWN`
- **Financial fields**:
  - `Quantity Transacted` → `quantity` (positive Decimal)
  - `Spot Price at Transaction` → `price` (optional Decimal)
  - `Spot Price Currency` → `quote_asset` (optional)
  - `Subtotal` or `Total (inclusive of fees)` → `value` (optional Decimal; total preferred)
  - `Fees` → `fee` (optional Decimal)
- **Timestamp**: `YYYY-MM-DD HH:MM:SS [timezone]` or ISO-8601 variants; timezone-aware
- **Identity**: Deterministic ID from timestamp, transaction type, asset, quantity, subtotal
- **Privacy**: No user IDs in standard Coinbase transaction reports; `Notes` preserved as source remark
- **Reconciliation boundary**: Coinbase transactions do not participate in Binance-specific transfer/convert reconciliation

### 4.4 Processing

| Component | File | Responsibility |
|---|---|---|
| `ProcessingPipeline` | `backend/processing/pipeline.py` | Orchestrate ingestion → adaptation → reconciliation → comments |
| `AdapterRegistry` | `backend/adapters/registry.py` | Map `(source, report_type)` to adapter classes |
| `CommentEngine` | `backend/processing/comments.py` | Preserve raw source remarks, strip user IDs |

`AdapterRegistry` is the single source of truth for adapter selection. It maps stable keys such as `("binance", "transaction_record")` and `("binance", "spot_trade_history")` to adapter classes. The pipeline delegates adapter resolution to the registry rather than containing exchange-specific branching logic. Unsupported `(source, report_type)` combinations raise `AdapterNotFoundError`.

### 4.5 Reconciliation

| Component | File | Responsibility |
|---|---|---|
| `DuplicateDetector` | `backend/reconciliation/duplicates.py` | Weighted duplicate detection with union-find grouping |
| `TransferReconciler` | `backend/reconciliation/transfers.py` | Generic transfer leg matching engine |
| `BinanceTransferRules` | `backend/reconciliation/binance_transfers.py` | Binance-specific transfer leg extraction |
| `ConvertReconciler` | `backend/reconciliation/converts.py` | Generic convert leg matching engine |
| `BinanceConvertRules` | `backend/reconciliation/binance_converts.py` | Binance-specific convert leg extraction |

### 4.6 API

| Endpoint | File | Responsibility |
|---|---|---|
| `GET /health` | `backend/main.py` | Health check |
| `POST /api/v1/ingest` | `backend/main.py` | Exchange detection and report-type classification |
| `POST /api/v1/process` | `backend/main.py` | Full pipeline processing |

---

## 5. Data Invariants

These invariants constitute the contract for future development:

1. **Decimal precision**: All financial fields (`quantity`, `price`, `value`, `fee`, `fee_value`) use `Decimal`. No silent float conversion.
2. **Timezone-aware timestamps**: All `timestamp` values must carry timezone info. Naive datetimes are rejected.
3. **Positive quantity**: `quantity` must be positive (`> 0`). Zero or negative quantities are rejected at the model level.
4. **Non-negative fees**: `fee` and `fee_value` must be non-negative (`>= 0`). Negative fees are rejected at the model level.
5. **BUY/SELL semantics**: `Side.BUY` means acquisition of `asset`; `Side.SELL` means disposal of `asset`. Quantity is always positive; direction is encoded in `side`.
6. **Fee semantics**: Fee is a non-negative `Decimal` in `fee_asset`. Invalid fees are rejected. Fee asset is preserved separately from `asset`.
7. **Asset/quote_asset relationship**: `asset` and `quote_asset` must differ for trades. Unresolved pairs may produce `quote_asset = None`; the raw source price is preserved in `price` for auditability.
8. **Deterministic transaction IDs**: Same input row always produces the same `transaction_id`. Trade ID takes precedence when present.
9. **Privacy**: User IDs are never embedded in `transaction_id`. Sensitive keys in `metadata` are rejected.
10. **Duplicate semantics**: Identical `transaction_id` is an exact duplicate. Strong-identifier buckets (`source_transaction_id`, `tx_hash`) are always evaluated regardless of size. Weak fingerprint buckets use configurable time-window partitioning to bound comparisons while preserving all valid candidate pairs.
11. **Reconciliation semantics**: Transfer and convert reconciliation identify relationships without deleting source transactions.
12. **Transaction preservation**: No reconciliation step removes or mutates transactions in the result set.
13. **Summary completeness**: `ProcessingSummary` counts transactions by all `TransactionType` values, including `SWAP`.

---

## 6. Known Technical Debt

### 6.1 Detector Robustness

- **Location**: `backend/ingestion/detector.py`
- **Current behavior**: Confidence scoring / threshold may be fragile for edge-case filenames or mixed column patterns.
- **Severity**: Medium
- **Why it matters**: Misidentification of source or report type causes incorrect adapter selection and silent data loss.
- **Blocking**: Non-blocking for current supported formats.

### 6.2 Adapter Selection

- **Location**: `backend/adapters/registry.py`
- **Status**: Resolved in M016. `ProcessingPipeline` now delegates to `AdapterRegistry`.
- **Current behavior**: Registry maps `(source, report_type)` to adapter classes. Unsupported combinations raise `AdapterNotFoundError`.
- **Severity**: Previously Low; now resolved.
- **Why it mattered**: Adding new exchanges or report types required code changes in the pipeline.
- **Blocking**: Non-blocking; resolved.

### 6.3 Detector Robustness

- **Location**: `backend/ingestion/detector.py`
- **Current behavior**: Confidence scoring hardened in M015. Required-column minimum (50%) and ambiguity detection added.
- **Severity**: Previously Medium; now Low.
- **Why it matters**: Misidentification of source or report type causes incorrect adapter selection and silent data loss.
- **Blocking**: Non-blocking for current supported formats.

### 6.4 Metadata Duplication

- **Location**: Adapters (`backend/adapters/binance/transaction_record.py`, `backend/adapters/binance/spot_trade_history.py`)
- **Current behavior**: Adapters duplicate canonical `source` inside `metadata["source"]`.
- **Severity**: Low
- **Why it matters**: Redundant data increases memory footprint and creates risk of inconsistency if the field diverges.
- **Blocking**: Non-blocking.

### 6.5 CommentEngine Coupling

- **Location**: `backend/processing/comments.py`
- **Current behavior**: `CommentEngine` relies on `source_remark` and contains Binance-specific rules (`BinanceCommentRules`).
- **Severity**: Low
- **Why it matters**: Tightly couples comment processing to Binance metadata shape; harder to generalize to other exchanges.
- **Blocking**: Non-blocking.

---

## 7. Test Contract

### Baseline

**252 tests passed, 0 failed** as of M017.

### Behavioral Guarantees Protected by Tests

- **Spot Trade History adaptation**: 51 tests in `test_spot_trade_history.py` covering timestamp parsing, pair resolution, side parsing, fee handling, value computation, deterministic IDs, asset/quote validation, and API integration.
- **Transaction Record adaptation**: Covered in `test_transaction_record.py`.
- **Pipeline integration**: Covered in `test_processing.py` (source detection, end-to-end processing, API endpoints).
- **Reconciliation boundaries (M013)**: 8 new tests in `test_spot_trade_history.py` and 1 in `test_processing.py`:
  - Spot BUY is not a transfer leg.
  - Spot SELL is not a transfer leg.
  - Spot BUY is not a convert leg.
  - Spot SELL is not a convert leg.
  - Spot trades participate in duplicate detection (exact duplicate classification).
  - Spot trades pass through CommentEngine without fabricated comments.
  - API processing of Spot Trade History returns zero transfer/convert matches.
  - Mixed-source processing (Transaction Record + Spot Trade History) preserves trade counts and isolation.

---

## 8. M010 File Condition

### 8.1 Corruption Analysis

| Property | Value |
|---|---|
| File size | 188,592 bytes |
| NUL byte count | 4,040 |
| NUL byte range | Byte positions 10,230 – 18,308 |
| Encoding | UTF-8 with embedded NUL corruption |
| Recoverability | Partial — the markdown audit sections at the start and end are readable; the middle section (embedded source-code dumps) contains systematic NUL-byte corruption. Stripping NUL bytes yields readable Python source, but the file is not considered a clean artifact. |

### 8.2 Git Recovery

- **Git repository**: Not present. `C:\Projects\CryptoClean` is not a Git repository.
- **Clean historical version**: Not found.
- **Backup copies**: None found in the repository.

### 8.3 Decision

The corrupted `M010_ARCHITECTURE_AUDIT.txt` is **not** replaced. It remains on disk for historical reference. `ARCHITECTURE_SPEC.md` (this document) is the authoritative architecture specification.

---

## 9. Files Created / Modified

| Action | Path |
|---|---|
| Created | `C:\Projects\CryptoClean\ARCHITECTURE_SPEC.md` |
| Read-only inspection | `C:\Projects\CryptoClean\M010_ARCHITECTURE_AUDIT.txt` |
| No application source files were modified. |

---

## 10. Next Recommended Task

**M018 — Additional Exchange Adapter (e.g., Bybit)**

With Coinbase adapter support proven in M017, the next milestone should focus on adding a third exchange adapter to further validate the registry design:

1. Implement `BybitTransactionRecordAdapter` using the existing canonical model.
2. Register it in `AdapterRegistry`.
3. Add Bybit-specific test fixtures and detector tests.
4. Verify the new adapter integrates with the existing pipeline, reconciliation, and comment engines without modification.
5. Document any Bybit-specific reconciliation boundaries.

This would further validate that the registry design consistently enables new exchange additions without pipeline changes.

---

## 11. M026 P2 Hardening Updates

### 11.1 Currency Validation Semantics

The engine validates currency compatibility before computing P&L:

- **Matching currencies**: P&L calculated normally
- **Mismatched currencies**: CURRENCY_MISMATCH warning emitted, P&L set to None
- **Missing proceeds currency**: CURRENCY_MISMATCH warning emitted, P&L set to None
- **Missing cost currency**: CURRENCY_MISMATCH warning emitted, P&L set to None
- **Both currencies missing**: No warning (both unknown), PnL computed without currency validation

### 11.2 Swap Fee Handling

Swap acquisition cost basis fallback behavior:

- **Normal base-asset fee**: Cost basis preserved from disposal proceeds
- **Base-asset fee equal to quantity**: Cost basis preserved
- **Base-asset fee exceeding quantity**: Cost basis preserved with THIRD_ASSET_FEE warning
- **Quote-asset fee**: Subtracted from fallback cost basis
- **Third-asset fee**: Cost basis preserved (fee not allocated)

### 11.3 Duplicate Detection Source Scoping

Duplicate detection distinguishes between same-source and cross-exchange identifiers:

- **Same transaction_id + same source**: Exact duplicate (score 100)
- **Same transaction_id + different source**: Not automatically duplicate
- **Same tx_hash across exchanges**: May match via transfer reconciliation
- **Same source + same tx_hash**: Probable duplicate

### 11.4 Swap Handler Pairing

Swap handler uses greedy pairing within timestamp windows:

- **Even-sized groups**: All transactions paired
- **Odd-sized groups**: All but last transaction paired, last marked unpaired
- **Unpaired swaps**: Marked as NON_ACCOUNTING with PARTIAL_SWAP_VALUATION warning

### 11.4.1 Multi-Hop Swap Limitation

The swap handler pairs transactions within a single timestamp window using greedy pairing. Multi-hop swaps (e.g., BTC → ETH → USDT) that span multiple timestamp windows are **not automatically linked**:

- Each hop is treated as an independent swap event
- Cost basis is computed per-hop using the disposal proceeds of the previous hop
- Users should ensure all hops of a multi-hop swap share the same timestamp window for correct pairing
- This is a known limitation; future work may add cross-window swap chain detection

### 11.5 New Warnings/Errors

- CURRENCY_MISMATCH: Extended to cover missing currency cases
- THIRD_ASSET_FEE: Extended to cover excessive base-asset fee on swap output

### 11.6 Technical Debt Status

- M021 P0/P1 findings: Remediated (M022)
- M023 P0 cross-asset FIFO: Remediated (M024)
- M025 P2 findings: Remediated (M026)
- M025 P3 findings: Remaining (see Remaining Risks)

### 11.7 Updated Test Baseline

**379 tests passed, 0 failed**

### 11.8 Next Milestone

**M033 — Post-Launch Monitoring and Customer Feedback**

Recommended focus areas:
1. Monitor Render deployment health
2. Onboard first customers
3. Gather feedback for future improvements
4. Plan feature enhancements based on customer needs
