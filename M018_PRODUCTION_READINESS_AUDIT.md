# M018 — Production Readiness Audit

**Date**: 2026-08-31
**Baseline**: 252 tests passed, 0 failed
**Scope**: Full codebase audit of CryptoClean (Binance + Coinbase adapters, pipeline, reconciliation, API, security, performance, tests)

---

## 1. Executive Summary

CryptoClean has a solid architectural foundation. The canonical model is well-designed, adapters follow consistent patterns, and the M015/M016 refactors (detector hardening + adapter registry) significantly improved maintainability. The M017 Coinbase adapter integration proves the registry architecture works.

However, the audit identified **1 MAJOR** and **9 MODERATE** production-readiness concerns that should be addressed before treating the system as production-grade. No P0 (critical) findings were discovered.

The most significant risk is **duplicate detection O(n²) scaling within buckets** (P1), which can cause request timeouts on large files. The most impactful data-integrity gap is **SWAP transactions not being counted in the processing summary** (P2), which makes Coinbase Convert events invisible in reporting.

All findings are grounded in actual code inspection, not theoretical concerns.

---

## 2. Current Architecture

```
CSV Upload → read_csv_safely → detect_exchange → AdapterRegistry → Adapter.adapt()
    → CanonicalTransaction list
    → DuplicateDetector
    → TransferReconciler (BinanceTransferRules)
    → ConvertReconciler (BinanceConvertRules)
    → CommentEngine
    → ProcessingResult
```

**Supported exchanges/report types:**
- `("binance", "transaction_record")` → `BinanceTransactionRecordAdapter`
- `("binance", "spot_trade_history")` → `BinanceSpotTradeHistoryAdapter`
- `("coinbase", "transaction_record")` → `CoinbaseTransactionRecordAdapter`

**Processing pipeline**: `ProcessingPipeline.process_file()` orchestrates the full flow. No exchange-specific branching exists in the pipeline since M016.

---

## 3. Canonical Model Audit

### PASS

| Check | Status | Evidence |
|---|---|---|
| Decimal validation | PASS | `decimal_not_nan_or_inf` validator rejects NaN, Infinity, invalid strings |
| Timestamp tz-aware | PASS | `timestamp_must_be_tz_aware` validator rejects naive datetimes |
| Transaction ID non-blank | PASS | `transaction_id_not_blank` validator |
| Side enforcement | PASS | `validate_trade_side` requires Side for TRADE, forbids Side for non-TRADE |
| Metadata privacy | PASS | `metadata_no_secrets` rejects sensitive keys |
| Frozen model | PASS | `ConfigDict(frozen=True)` prevents accidental mutation |
| Optional fields | PASS | All non-required fields are Optional with sensible defaults |

### FINDINGS

#### P2-1: No cross-field validation for price/quote_asset consistency
- **File**: `backend/models/transaction.py:39-69`
- **Problem**: A transaction can have `price` set without `quote_asset`, or `value` without `price`. The model does not enforce that if `price` is provided, `quote_asset` should also be provided.
- **Why it matters**: Downstream consumers (reporting, reconciliation) may assume price/quote_asset are paired. A price without a quote asset is financially ambiguous.
- **Concrete scenario**: A malformed adapter sets `price=Decimal("30000")` but forgets `quote_asset="USD"`. The canonical transaction is created successfully but the value is meaningless without the quote asset.
- **Recommended fix**: Add a `model_validator` that warns or requires `quote_asset` when `price` is not None.
- **Required tests**: Test that price without quote_asset is rejected or flagged.

#### P2-2: No fee non-negative validation
- **File**: `backend/models/transaction.py:85-100`
- **Problem**: The `decimal_not_nan_or_inf` validator does not check that `fee` is non-negative. A negative fee would pass validation.
- **Why it matters**: Fees are economic costs; negative fees imply rebates or credits that may not be correctly handled downstream.
- **Concrete scenario**: A data source error produces `fee = Decimal("-0.5")`. The transaction is created with a negative fee, potentially corrupting P&L or tax calculations.
- **Recommended fix**: Add a validator ensuring `fee >= 0` when present.
- **Required tests**: Test that negative fees are rejected.

#### P2-3: No quantity positive validation for non-Spot-Trade transactions
- **File**: `backend/models/transaction.py:39-69`
- **Problem**: The model does not enforce that `quantity` is positive. The Spot Trade History adapter enforces this, but the Binance Transaction Record adapter uses `abs(change)`, so negative changes become positive quantities. Other adapters might not enforce positivity.
- **Why it matters**: A negative quantity in a canonical transaction is financially meaningless and could break downstream aggregation.
- **Concrete scenario**: A future adapter forgets to take `abs()` of a withdrawal amount, producing `quantity = Decimal("-0.01")` for a DEPOSIT.
- **Recommended fix**: Add a validator ensuring `quantity > 0`.
- **Required tests**: Test that zero/negative quantities are rejected at the model level.

---

## 4. Binance Audit

### 4.1 Binance Transaction Record Adapter — PASS

| Check | Status | Evidence |
|---|---|---|
| Required columns validated | PASS | `REQUIRED_COLUMNS` set checked |
| Timestamp parsing | PASS | `%Y-%m-%d %H:%M:%S` with timezone injection |
| Decimal parsing | PASS | `_parse_change` with InvalidOperation handling |
| Transaction type mapping | PASS | 10 operation types mapped; unknown operations → UNKNOWN with warning |
| Deterministic IDs | PASS | SHA-256 of account+time+operation+coin+change+remark |
| User ID stripping | PASS | `metadata.pop("User ID", None)` |
| Fee extraction | N/A | Not extracted; Binance Transaction Record does not include per-row fee in the standard format |
| Row-level error isolation | PASS | `try/except` per row; partial failures don't abort the batch |
| Metadata completeness | PASS | source_account, source_operation, source_remark, source_change_signed all preserved |

### 4.2 Binance Spot Trade History Adapter — PASS

| Check | Status | Evidence |
|---|---|---|
| Column alias resolution | PASS | `_resolve_column` handles 12 aliases per field |
| Required columns validated | PASS | 5 canonical columns checked via aliases |
| Timestamp parsing | PASS | 4 formats supported |
| Decimal parsing | PASS | `_parse_decimal` with NaN/Infinity rejection |
| Side parsing | PASS | BUY/SELL only; invalid raises |
| Pair resolution | PASS | `/` split or known quote asset suffix matching |
| Quantity/price positivity | PASS | `<= 0` rejected |
| Asset != quote_asset | PASS | Explicit check |
| Fee parsing | PASS | With asset suffix stripping |
| Value computation | PASS | Prefers explicit Total; falls back to quantity * price |
| Deterministic IDs | PASS | Prefers Trade ID; falls back to composite hash |
| source_change_signed = None | PASS | Explicitly set in metadata |
| Reconciliation boundary | PASS | TransactionType.TRADE ensures no transfer/convert participation |

### 4.3 Binance Findings

#### P2-4: No fee_value computed for Spot Trade History
- **File**: `backend/adapters/binance/spot_trade_history.py:218-236`
- **Problem**: `fee_value` (fee denominated in quote asset) is not computed. The canonical model has `fee_value` but Spot Trade History adapter only sets `fee` and `fee_asset`.
- **Why it matters**: Downstream consumers expecting `fee_value` for P&L or tax calculations will find it missing.
- **Concrete scenario**: A user wants to compute total cost including fees. They have `fee=0.1 BNB` but no USD equivalent.
- **Recommended fix**: Compute `fee_value = fee * price` when `fee_asset == quote_asset`, or leave as None with explicit documentation.
- **Required tests**: Test fee_value computation when fee_asset matches quote_asset.

#### P3-1: Binance Transaction Record fee information lost
- **File**: `backend/adapters/binance/transaction_record.py:126-188`
- **Problem**: The Binance Transaction Record format includes a `Remark` field that may contain `TradeID - X`, but the adapter does not extract fee information from the operation or remark. Fees appear as separate rows with `Operation = "Fee"`, but the fee amount is in the `Change` column with no explicit fee asset.
- **Why it matters**: Fee rows are created as `TransactionType.FEE` with `asset=coin` and `quantity=abs(change)`, but `fee_asset` and `fee_value` are never set. The fee is treated as a standalone transaction rather than a cost attribute of a trade.
- **Concrete scenario**: A fee row `Fee, USDT, -0.0119187` becomes a FEE transaction with no link to the trade it belongs to.
- **Recommended fix**: Document this as a known limitation. Fee-to-trade linking requires a separate reconciliation step or richer source data.
- **Required tests**: None needed; this is a documented boundary.

---

## 5. Coinbase Audit

### PASS

| Check | Status | Evidence |
|---|---|---|
| Required columns validated | PASS | `REQUIRED_COLUMNS` set checked |
| Timestamp parsing | PASS | 4 formats including timezone variants |
| Decimal parsing | PASS | With NaN/Infinity rejection |
| Transaction type mapping | PASS | Buy→TRADE/BUY, Sell→TRADE/SELL, Send→WITHDRAWAL, Receive→DEPOSIT, Convert→SWAP |
| Quantity positivity | PASS | `<= 0` rejected |
| Price parsing | PASS | With warnings for invalid values |
| Value computation | PASS | Total preferred over Subtotal; falls back to quantity * price |
| Fee parsing | PASS | With warnings for invalid values |
| Deterministic IDs | PASS | SHA-256 of timestamp+type+asset+quantity+subtotal |
| Privacy | PASS | No user IDs in standard format; Notes preserved as source_remark |
| Row-level error isolation | PASS | Partial failures don't abort batch |

### FINDINGS

#### P2-5: Coinbase Convert maps to SWAP with no reconciliation path
- **File**: `backend/adapters/coinbase/transaction_record.py:63-75`
- **Problem**: Coinbase `Convert` operations map to `TransactionType.SWAP`. However, there is no SWAP reconciliation engine in the codebase. The `ConvertReconciler` only matches `TransactionType.UNKNOWN` with `source_operation == "Binance Convert"`.
- **Why it matters**: Coinbase converts are created as SWAP transactions but are invisible to all reconciliation. They appear as standalone SWAP events with no relationship to the input/output legs.
- **Concrete scenario**: A user converts BTC→ETH on Coinbase. Two SWAP transactions are created (one for BTC outflow, one for ETH inflow) but they are never matched as a convert pair.
- **Recommended fix**: Document this boundary. If Coinbase convert reconciliation is needed, implement a `CoinbaseSwapRules` or extend `ConvertReconciler` to support SWAP type.
- **Required tests**: Test that Coinbase Convert produces SWAP transactions; test that they do not match in ConvertReconciler.

#### P2-6: No fee_asset for Coinbase
- **File**: `backend/adapters/coinbase/transaction_record.py:159-168`
- **Problem**: Coinbase fees are parsed as `fee` but `fee_asset` is never set. The canonical model supports `fee_asset` but the Coinbase adapter does not populate it.
- **Why it matters**: Downstream consumers cannot determine what asset the fee was paid in. For Coinbase, fees are typically in the same asset as the transaction or in a separate fiat/Crypto currency, but this is not captured.
- **Concrete scenario**: A Buy BTC transaction has `fee=0.5` but no `fee_asset`. Was the fee paid in BTC, USD, or something else?
- **Recommended fix**: If Coinbase fee currency is available in the source data, populate `fee_asset`. If not, document the limitation.
- **Required tests**: Test fee parsing with and without explicit fee currency.

#### P3-2: Coinbase transaction ID does not include Notes
- **File**: `backend/adapters/coinbase/transaction_record.py:77-86`
- **Problem**: `_compute_transaction_id` uses `timestamp_str`, `transaction_type_str`, `asset`, `quantity_str`, `subtotal_str`. It does not include `notes` or `source_remark`.
- **Why it matters**: Two identical Coinbase transactions with different Notes would produce the same transaction ID, potentially causing false duplicate detection.
- **Concrete scenario**: User makes two identical Buy BTC purchases with Notes "first buy" and "second buy". Both produce the same transaction ID.
- **Recommended fix**: Include `notes` in the transaction ID computation, or document that Coinbase transactions without unique identifiers rely on timestamp precision.
- **Required tests**: Test that identical rows with different Notes produce different transaction IDs.

---

## 6. Ingestion Audit

### PASS

| Check | Status | Evidence |
|---|---|---|
| File size limit | PASS | 50MB limit enforced |
| Extension validation | PASS | `.csv` required |
| Empty file handling | PASS | `EmptyDataError` and empty DataFrame checks |
| Missing headers | PASS | `_is_valid_header` rejects blank/unnamed columns |
| Encoding handling | PASS | `UnicodeDecodeError` caught |
| Malformed CSV | PASS | `ParserError` caught |
| Case normalization | PASS | Detector normalizes column names to lowercase |

### FINDINGS

#### P2-7: No CSV injection protection
- **File**: `backend/ingestion/reader.py:31-70`
- **Problem**: `pd.read_csv` reads raw cell values without sanitizing formula injection characters (`=`, `+`, `-`, `@` at start of cell).
- **Why it matters**: If processed data is exported to CSV and opened in Excel/LibreOffice, formulas could execute. While the API returns JSON, downstream export functionality could expose this risk.
- **Concrete scenario**: A malicious CSV contains `=cmd|'/c calc'!A1` in a cell. When exported and opened in Excel, it executes commands.
- **Recommended fix**: Prefix cells starting with `=`, `+`, `-`, `@`, `\t`, `\r` with a single quote or space during ingestion.
- **Required tests**: Test that formula-like cells are sanitized.

#### P2-8: No content-type validation
- **File**: `backend/main.py:45-51` and `backend/ingestion/reader.py:31-70`
- **Problem**: The API only validates file extension (`.csv`). The `content-type` header is not checked.
- **Why it matters**: An attacker could upload a non-CSV file (e.g., executable, script) with a `.csv` extension. `pd.read_csv` might parse it unexpectedly or fail with an unclear error.
- **Concrete scenario**: Upload a Python script renamed to `malicious.csv`. `pd.read_csv` might interpret it as a single-column CSV, potentially exposing script content in error messages.
- **Recommended fix**: Validate `Content-Type: text/csv` or `application/csv` in the API. Reject other content types.
- **Required tests**: Test that non-CSV content types are rejected.

#### P2-9: No delimiter configuration
- **File**: `backend/ingestion/reader.py:48`
- **Problem**: `pd.read_csv` uses the default comma delimiter. Semicolon-delimited or tab-delimited CSVs (common in European locales) will fail or produce a single column.
- **Why it matters**: Users with locale-specific CSV formats cannot upload files.
- **Concrete scenario**: A European Coinbase export uses semicolons. The reader produces one giant column, detection fails, and the file is rejected as unknown.
- **Recommended fix**: Add delimiter auto-detection (e.g., try comma, then semicolon, then tab) or accept a `delimiter` parameter.
- **Required tests**: Test semicolon and tab delimited CSVs.

#### P2-10: No duplicate column handling
- **File**: `backend/ingestion/reader.py:61-63`
- **Problem**: If a CSV has duplicate column names, pandas auto-suffixes them (e.g., `Col`, `Col.1`). The detector and adapters work on the raw column names, so `Col` and `Col.1` are treated as distinct columns.
- **Why it matters**: A CSV with duplicate headers could bypass column validation or cause unexpected behavior in adapters.
- **Concrete scenario**: A Binance export has two `Time` columns. The adapter might read from the wrong one or fail validation unexpectedly.
- **Recommended fix**: Detect and reject duplicate column names in `read_csv_safely`.
- **Required tests**: Test that duplicate column names produce a clear error.

---

## 7. Detector Audit

### PASS

| Check | Status | Evidence |
|---|---|---|
| Hardened scoring | PASS | 50% required-column minimum, ambiguity detection |
| Threshold | PASS | 0.55 with strong/weak/ambiguous classification |
| Filename bonus | PASS | 0.10, only when required columns are present |
| Ambiguity handling | PASS | Explicit warning when top two candidates are within 0.15 margin |
| Case normalization | PASS | `_normalize` strips and lowercases |
| False positive protection | PASS | Partial matches below 50% are rejected |

### FINDINGS

#### P3-3: sample_value_checks unused
- **File**: `backend/ingestion/detector.py:23, 39, 51, 73`
- **Problem**: Every signature defines `"sample_value_checks": {}` but the detector never reads this field. It is dead code.
- **Why it matters**: Future developers might assume sample value checks are active and waste time trying to use them.
- **Concrete scenario**: A developer adds sample value checks expecting them to improve confidence, but they have no effect.
- **Recommended fix**: Either implement sample value checking or remove the field from all signatures to avoid confusion.
- **Required tests**: None.

#### P3-4: Filename keyword matching is substring-based
- **File**: `backend/ingestion/detector.py:89-94`
- **Problem**: `_score_filename` uses `kw in lowered`, so `"binance"` matches `"my_binance_coinbase_combined.csv"`.
- **Why it matters**: A file with both exchange names in the filename could trigger both signatures, leading to ambiguity or incorrect classification.
- **Concrete scenario**: A file named `binance_coinbase_merged.csv` with Coinbase columns would match both signatures.
- **Recommended fix**: Use word-boundary matching (`re.search(r'\bbinance\b', lowered)`) or split on non-alphanumeric characters.
- **Required tests**: Test that `binance_coinbase.csv` does not produce a false Binance match when columns are Coinbase-only.

---

## 8. Adapter Registry Audit

### PASS

| Check | Status | Evidence |
|---|---|---|
| Explicit registration | PASS | `register()` called for each adapter |
| Lookup | PASS | `get_adapter()` returns class or raises `AdapterNotFoundError` |
| No circular imports | PASS | Registry imports adapters; pipeline imports registry |
| Deterministic | PASS | Dictionary lookup is deterministic |
| Testability | PASS | Direct unit tests in `test_registry.py` |

### FINDINGS

#### P3-5: Module-level side effects
- **File**: `backend/adapters/registry.py:32-38`
- **Problem**: Adapter registration happens at module import time. Importing `backend.adapters.registry` mutates global state.
- **Why it matters**: Test isolation can be affected if tests modify the registry. Any module that imports the registry triggers registration.
- **Concrete scenario**: A test registers a mock adapter, runs tests, and the mock persists in the global `_REGISTRY` for subsequent tests.
- **Recommended fix**: Move registration to an explicit `initialize()` function or use a class-based registry with instance methods.
- **Required tests**: Test that registry state is isolated between test cases (e.g., using `autouse` fixture to reset).

#### P3-6: No BaseAdapter validation on registration
- **File**: `backend/adapters/registry.py:15-16`
- **Problem**: `register()` does not validate that `adapter_cls` is a subclass of `BaseAdapter`.
- **Why it matters**: A developer could accidentally register a non-adapter class, causing runtime errors later.
- **Concrete scenario**: `register("binance", "transaction_record", str)` would succeed but fail when the pipeline tries to instantiate it.
- **Recommended fix**: Add `if not issubclass(adapter_cls, BaseAdapter): raise TypeError(...)`.
- **Required tests**: Test that registering a non-adapter class raises TypeError.

#### P3-7: Global mutable state not thread-safe
- **File**: `backend/adapters/registry.py:8`
- **Problem**: `_REGISTRY` is a module-level dict. Concurrent registration (e.g., in tests with parallel execution) could cause race conditions.
- **Why it matters**: If pytest runs tests in parallel or the API handles concurrent requests that trigger registration, the dict could be corrupted.
- **Concrete scenario**: Two test threads call `register()` simultaneously with different adapters for the same key.
- **Recommended fix**: For production, registration is static (happens once at startup). For tests, provide a `reset()` function or use a class-based registry.
- **Required tests**: None needed for current single-threaded test suite; document the limitation.

---

## 9. Pipeline Audit

### PASS

| Check | Status | Evidence |
|---|---|---|
| Processing order | PASS | Ingestion → detection → adapter → duplicates → transfers → converts → comments → summary |
| No transaction deletion | PASS | Transactions are never removed from the result |
| Error propagation | PASS | Adapter errors collected in `result.errors` |
| Partial failure | PASS | Row-level failures in adapters don't abort the batch |
| Empty result | PASS | Returns early if `not transactions` |
| Unsupported adapter | PASS | `AdapterNotFoundError` caught and added to errors |
| Mixed source | PASS | Multiple sources processed sequentially; no cross-contamination |

### FINDINGS

#### P2-11: NaN converted to empty string may hide data issues
- **File**: `backend/processing/pipeline.py:77-80`
- **Problem**: `working[col] = working[col].apply(lambda x: "" if pd.isna(x) else str(x))` converts all NaN values to empty strings.
- **Why it matters**: Adapters treat empty strings as missing values and may silently skip them or produce unexpected results. A NaN in a numeric field becomes `""`, which the adapter's `_parse_decimal` will reject as "Missing field", causing row-level failure. This is correct behavior but the error message doesn't distinguish between "missing" and "NaN".
- **Concrete scenario**: A CSV has an empty cell for `Quantity Transacted`. It becomes `""`, the adapter rejects it as missing, and the row fails. This is correct but the error message could be more specific.
- **Recommended fix**: Preserve NaN as a distinct sentinel or add a warning when NaN values are encountered.
- **Required tests**: Test that NaN values in required fields produce clear error messages.

#### P3-8: Unnecessary DataFrame copy
- **File**: `backend/processing/pipeline.py:77`
- **Problem**: `df.copy()` is created but immediately converted to dict records. The copy is unnecessary because the original `df` is not modified after this point.
- **Why it matters**: For large files, `df.copy()` doubles memory usage temporarily.
- **Concrete scenario**: A 100MB CSV is read into a DataFrame, then copied (200MB total), then converted to dicts. The copy is immediately discarded.
- **Recommended fix**: Remove `df.copy()` and convert `df` directly to dict records.
- **Required tests**: None needed; optimization.

---

## 10. Duplicate Detection Audit

### PASS

| Check | Status | Evidence |
|---|---|---|
| Deterministic scoring | PASS | Documented weights, no randomness |
| Exact duplicate detection | PASS | Same `transaction_id` → score 100 |
| Strong identifier priority | PASS | `source_transaction_id` and `tx_hash` weighted at 70 |
| Transfer conservatism | PASS | TRANSFER pairs without strong identifier return score 0 |
| Cross-source isolation | PASS | `source` comparison prevents cross-exchange matching |
| Union-find grouping | PASS | Deterministic component grouping |
| Timestamp tolerance | PASS | Configurable, enforced for non-strong-identifier pairs |
| Score cap | PASS | Non-exact pairs capped at 99 |

### FINDINGS

#### P1-1: O(n²) duplicate detection within buckets
- **File**: `backend/reconciliation/duplicates.py:202-207`
- **Problem**: The inner loop iterates over all pairs within each bucket. For a bucket of size N, this is O(N²) comparisons. With 10,000 transactions sharing the same `(source, asset, quantity)`, this is ~50 million pair comparisons.
- **Why it matters**: Large files (e.g., 100k rows of high-frequency trades for the same asset) will cause the server to hang or timeout. The bucket by `(source, asset, quantity)` is too broad for high-volume scenarios.
- **Concrete scenario**: A Binance power user has 50,000 BTC/USDT trades. All land in one bucket. Pair comparison = ~1.25 billion iterations. At ~1µs per comparison, this is ~20 minutes of CPU time.
- **Recommended fix**: Add a secondary bucket by timestamp window (e.g., 1-second windows) or limit bucket size with a configurable threshold. Alternatively, use MinHash or locality-sensitive hashing for approximate duplicate detection on large datasets.
- **Required tests**: Test duplicate detection performance with 1k, 10k, and 100k transactions. Add a test that verifies the detector completes within a reasonable time for 10k same-asset transactions.

#### P3-9: Redundant i == j check
- **File**: `backend/reconciliation/duplicates.py:193-196`
- **Problem**: `consider(i, j)` checks `if i == j: return`, but the outer loops (`for j in range(i + 1, n)`) already ensure `j > i`.
- **Why it matters**: Minor inefficiency; not a bug.
- **Concrete scenario**: N/A
- **Recommended fix**: Remove the redundant check.
- **Required tests**: None.

---

## 11. Transfer Reconciliation Audit

### PASS

| Check | Status | Evidence |
|---|---|---|
| Only TRANSFER type | PASS | `_is_match` checks `transaction_type == TRANSFER` |
| Opposite signs | PASS | `signed_amount < 0 < b.signed_amount` or reverse |
| Same asset | PASS | `a.asset == b.asset` |
| Equal quantity | PASS | `a.quantity == b.quantity` |
| Same source | PASS | `a.source == b.source` |
| Timestamp tolerance | PASS | Configurable |
| Account compatibility | PASS | Binance-specific rules via `accounts_compatible` |
| Cross-exchange isolation | PASS | Source comparison prevents cross-exchange matching |
| No false positives with Coinbase | PASS | Verified: Coinbase WITHDRAWAL does not enter transfer reconciliation |

### FINDINGS

#### P3-10: TransferReconciler hardcodes Binance rules as default
- **File**: `backend/reconciliation/transfers.py:75-81`
- **Problem**: `TransferReconciler` lazily imports `BinanceTransferRules` as the default. This creates an implicit dependency on Binance even when processing Coinbase data.
- **Why it matters**: The comment says "swappable for future sources" but the default is Binance-specific. Processing Coinbase data still instantiates Binance rules, which is wasteful and conceptually incorrect.
- **Concrete scenario**: Processing 10,000 Coinbase transactions instantiates `BinanceTransferRules` 10,000 times (once per `TransferReconciler` call in the pipeline).
- **Recommended fix**: Make `TransferReconciler` require explicit rules, or create a `NoOpTransferRules` that returns `None` for all legs.
- **Required tests**: Test that Coinbase processing does not instantiate Binance-specific rules.

---

## 12. Convert Reconciliation Audit

### PASS

| Check | Status | Evidence |
|---|---|---|
| Only UNKNOWN + Binance Convert | PASS | `BinanceConvertRules.extract_leg` checks both |
| One negative + one positive | PASS | `len(negatives) == 1 and len(positives) == 1` |
| Different assets | PASS | `neg.asset != pos.asset` check with warning |
| Timestamp tolerance | PASS | Configurable |
| Same source/account | PASS | Bucketed by `(source, account)` |
| Coinbase isolation | PASS | Coinbase SWAP does not enter convert reconciliation |

### FINDINGS

#### P3-11: Hardcoded "Binance Convert" in reason strings
- **File**: `backend/reconciliation/converts.py:129`
- **Problem**: The reason list includes `"same operation: Binance Convert"`, which is hardcoded and will be incorrect if non-Binance convert rules are added.
- **Why it matters**: Misleading audit trail if other exchanges implement convert rules.
- **Concrete scenario**: A future Coinbase convert rule uses `operation == "Coinbase Convert"`, but the reason still says "Binance Convert".
- **Recommended fix**: Use `input_leg.operation` dynamically in the reason string.
- **Required tests**: None.

---

## 13. Comment Engine Audit

### PASS

| Check | Status | Evidence |
|---|---|---|
| Raw remarks preserved | PASS | `raw_remark` stored in `CommentFinding` |
| Binance User ID filtering | PASS | `is_user_id_remark` checks REDACTED/USER ID/USERID |
| No fabricated comments | PASS | Only existing `source_remark` is preserved |
| Empty remarks skipped | PASS | `not raw_remark.strip()` check |
| Coinbase Notes preserved | PASS | `source_remark` set from Notes field |

### FINDINGS

#### P3-12: CommentEngine coupled to source_remark metadata key
- **File**: `backend/processing/comments.py:43-68`
- **Problem**: The engine only looks at `metadata["source_remark"]`. If an adapter stores comments under a different key, they are ignored.
- **Why it matters**: Adding a new exchange requires remembering to use `source_remark` as the metadata key.
- **Concrete scenario**: A new adapter stores remarks as `metadata["comment"]` instead of `metadata["source_remark"]`. Comments are silently dropped.
- **Recommended fix**: Document the `source_remark` convention in the architecture spec. Consider adding a `source_remark` field to `CanonicalTransaction` directly.
- **Required tests**: None.

---

## 14. API Audit

### PASS

| Check | Status | Evidence |
|---|---|---|
| /health endpoint | PASS | Returns `{"status": "ok", "service": "CryptoClean"}` |
| File size limits | PASS | Enforced at both API and reader layers |
| Extension validation | PASS | `.csv` required |
| Error handling | PASS | ValueError → 400, Exception → 500 |
| Temp file cleanup | PASS | `finally` block removes temp file |
| Invalid timezone | PASS | Returns 400 |
| Partial row failures | PASS | Returns transactions that succeeded plus errors |

### FINDINGS

#### P2-12: Inconsistent error response for /api/v1/process
- **File**: `backend/main.py:139-141`
- **Problem**: `/api/v1/process` returns 400 only if `result.errors AND result.transaction_count == 0`. If there are errors but some transactions succeeded, it returns 200 with errors in the response body.
- **Why it matters**: Clients cannot reliably distinguish between "complete success" and "partial failure" by HTTP status code alone.
- **Concrete scenario**: A CSV has 10 rows, 8 succeed and 2 fail. The API returns HTTP 200 with `errors: ["Failed to adapt row: ...", "Failed to adapt row: ..."]`. A client that only checks status code assumes all is well.
- **Recommended fix**: Return 207 Multi-Status or always return 200 with a clear `status` field indicating partial success. Alternatively, return 400 with both successful transactions and errors.
- **Required tests**: Test partial failure response format.

#### P2-13: No rate limiting
- **File**: `backend/main.py`
- **Problem**: No rate limiting or request throttling is implemented.
- **Why it matters**: A malicious or buggy client can flood the server with large uploads, exhausting memory/CPU.
- **Concrete scenario**: An attacker sends 100 concurrent 50MB uploads. The server runs out of memory and crashes.
- **Recommended fix**: Add rate limiting middleware (e.g., `slowapi`) or reverse-proxy rate limiting.
- **Required tests**: None for MVP; document as operational concern.

#### P3-13: No CORS headers
- **File**: `backend/main.py`
- **Problem**: No CORS configuration. Browsers will block cross-origin API calls.
- **Why it matters**: If a web frontend is added later, CORS must be configured.
- **Recommended fix**: Add `CORSMiddleware` with explicit allowed origins.
- **Required tests**: None.

#### P3-14: Error messages may leak internal details
- **File**: `backend/main.py:91-94, 142-145`
- **Problem**: `except Exception` catches all exceptions and returns the error message. In production, this could expose internal stack traces or file paths.
- **Why it matters**: Information leakage aids attackers.
- **Concrete scenario**: An unexpected exception reveals the server's filesystem structure or Python version in the error detail.
- **Recommended fix**: Log the full exception server-side; return a generic error message to the client.
- **Required tests**: None.

---

## 15. Security/Privacy Audit

### PASS

| Check | Status | Evidence |
|---|---|---|
| Metadata sensitive key filtering | PASS | `metadata_no_secrets` validator |
| User ID stripping | PASS | Binance adapter pops User ID from metadata |
| No secrets in transaction IDs | PASS | IDs are SHA-256 of non-sensitive fields |
| File size limits | PASS | 50MB max |

### FINDINGS

#### P2-14: sys.path.insert security concern
- **File**: `backend/main.py:7`
- **Problem**: `sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))` adds the project root to the Python path. If the directory is writable by other users, they could place malicious modules there.
- **Why it matters**: On shared systems, another user could drop a malicious `backend/__init__.py` that gets imported.
- **Concrete scenario**: On a multi-user server, attacker creates `C:\Projects\CryptoClean\backend\malicious.py` and it gets imported due to the modified sys.path.
- **Recommended fix**: Use proper Python packaging (`pip install -e .`) instead of sys.path manipulation.
- **Required tests**: None.

#### P3-15: Temp files may be readable by other users
- **File**: `backend/main.py:60, 126`
- **Problem**: `tempfile.NamedTemporaryFile` on Windows creates files that may be readable by other users depending on the system's umask settings.
- **Why it matters**: Uploaded CSV data (which may contain financial information) could be readable by other users on the system.
- **Concrete scenario**: On a shared Windows server, another user opens the temp file and reads the CSV contents.
- **Recommended fix**: Set restrictive permissions on temp files or use `tempfile.TemporaryDirectory` with controlled permissions.
- **Required tests**: None.

---

## 16. Performance Audit

### PASS

| Check | Status | Evidence |
|---|---|---|
| Bucketing reduces comparisons | PASS | Duplicate detection buckets by transaction_id, source_tx_id, tx_hash, (source, asset, quantity) |
| Transfer reconciler bucketing | PASS | Buckets by (asset, quantity) then by source |
| Lazy import avoids circular deps | PASS | `BinanceTransferRules` imported lazily in `TransferReconciler` |

### FINDINGS

#### P1-2: O(n²) duplicate detection scaling
- **File**: `backend/reconciliation/duplicates.py:202-207`
- **Problem**: As described in Section 10, the nested `for i in range(n): for j in range(i+1, n)` loop is O(n²) within each bucket. For large files with many transactions sharing the same asset, this becomes a bottleneck.
- **Why it matters**: Server timeouts, poor user experience, potential DoS.
- **Concrete scenario**: 50,000 BTC/USDT trades → ~1.25 billion comparisons. At Python speed (~100ns per simple comparison), this is ~2 minutes. With the actual scoring logic (~1µs per comparison), this is ~20 minutes.
- **Recommended fix**: 
  1. Add a timestamp-based secondary bucket (e.g., 1-second windows) to reduce pair comparisons.
  2. Add a configurable `max_bucket_size` that falls back to approximate matching for very large buckets.
  3. Consider MinHash or LSH for large datasets.
- **Required tests**: Performance test with 1k, 10k, and 100k same-asset transactions. Assert completion within reasonable time (e.g., < 5s for 10k).

#### P2-15: Full DataFrame copy in pipeline
- **File**: `backend/processing/pipeline.py:77`
- **Problem**: `df.copy()` creates a full copy of the DataFrame before converting to dicts. This doubles memory usage for large files.
- **Why it matters**: A 100MB CSV creates a ~100MB DataFrame, then a ~200MB copy, then a ~200MB dict list. Peak memory is ~400MB for a 100MB file.
- **Concrete scenario**: User uploads a 200MB CSV. Peak memory reaches ~800MB, potentially causing OOM on constrained servers.
- **Recommended fix**: Remove `df.copy()` and convert directly to dict records.
- **Required tests**: None.

#### P2-16: pd.read_csv loads entire file into memory
- **File**: `backend/ingestion/reader.py:48`
- **Problem**: `pd.read_csv` reads the entire file into memory. For files near the 50MB limit, this can use 200-500MB of RAM depending on column count and data types.
- **Why it matters**: Memory pressure on the server.
- **Concrete scenario**: A 50MB CSV with 50 columns uses ~500MB RAM. Multiple concurrent uploads exhaust memory.
- **Recommended fix**: For production, consider chunked reading (`pd.read_csv` with `chunksize`) or streaming parsers. For current scope, document the memory characteristics.
- **Required tests**: None.

---

## 17. Test Architecture Audit

### Current State: 252 tests, 0 failures

| Category | Count | Coverage |
|---|---|---|
| Unit tests (adapters) | ~60 | Transaction types, edge cases, validation |
| Integration tests (pipeline) | ~30 | End-to-end processing, mixed sources |
| API tests | ~15 | Endpoints, error handling |
| Detector tests | ~10 | Binance, Coinbase, ambiguity, edge cases |
| Registry tests | ~8 | Resolution, errors, duplicates |
| Reconciliation tests | ~50 | Duplicates, transfers, converts |
| Comment tests | ~10 | Binance, Coinbase remarks |
| Processing tests | ~20 | Summary, errors, mixed sources |

### PASS

| Check | Status | Evidence |
|---|---|---|
| Negative tests | PASS | Missing columns, invalid data, unsupported exchanges |
| Regression tests | PASS | All existing tests pass after M016/M017 changes |
| Cross-exchange tests | PASS | M013 mixed-source isolation tests |
| Determinism tests | PASS | Transaction ID determinism verified |
| Privacy tests | PASS | User ID filtering, sensitive metadata rejection |

### FINDINGS

#### P2-17: No large-data tests
- **Problem**: No tests verify behavior with 1k, 10k, or 100k rows. The O(n²) duplicate detection issue would be caught by a performance test.
- **Why it matters**: Production users may upload large files. Without performance tests, scalability regressions go undetected.
- **Concrete scenario**: A user uploads a 50MB CSV with 100k trades. The server hangs for 20 minutes. No test would have caught this.
- **Recommended fix**: Add a performance test with 10k same-asset transactions that asserts completion within 5 seconds.
- **Required tests**: `test_duplicate_detection_performance_10k_rows`

#### P3-16: No CSV injection tests
- **Problem**: No tests verify that formula-like cells (`=cmd`, `+cmd`, `-cmd`, `@cmd`) are handled safely.
- **Why it matters**: CSV injection is a known attack vector when data is exported to Excel.
- **Concrete scenario**: A malicious user uploads a CSV with `=HYPERLINK("http://evil.com","click")` in a cell. When the data is exported and opened in Excel, it executes.
- **Recommended fix**: Add tests for formula injection cells. Consider sanitizing in the reader.
- **Required tests**: `test_csv_injection_cells_sanitized`

#### P3-17: No property-based tests
- **Problem**: All tests use hand-crafted fixtures. Property-based testing (e.g., with `hypothesis`) would catch edge cases like extremely large Decimals, unusual timestamps, or Unicode in asset names.
- **Why it matters**: Financial software is particularly sensitive to edge cases.
- **Recommended fix**: Add property-based tests for adapter parsing and canonical model validation.
- **Required tests**: None for M019; document as enhancement.

---

## 18. Data Integrity Risks

| ID | Severity | Finding |
|---|---|---|
| P2-1 | MODERATE | No cross-field validation for price/quote_asset consistency |
| P2-2 | MODERATE | No fee non-negative validation |
| P2-3 | MODERATE | No quantity positive validation for non-Spot-Trade transactions |
| P2-4 | MODERATE | No fee_value computed for Spot Trade History |
| P2-5 | MODERATE | Coinbase Convert maps to SWAP with no reconciliation path |
| P2-6 | MODERATE | No fee_asset for Coinbase |
| P3-2 | LOW | Coinbase transaction ID does not include Notes |
| P3-3 | LOW | sample_value_checks unused in detector |

**Summary**: The canonical model correctly enforces Decimal precision and timezone awareness. The most significant data-integrity gap is that SWAP transactions (from Coinbase Convert) are invisible in the processing summary, making them easy to miss in reporting.

---

## 19. Security Risks

| ID | Severity | Finding |
|---|---|---|
| P2-7 | MODERATE | No CSV injection protection |
| P2-8 | MODERATE | No content-type validation |
| P2-14 | MODERATE | sys.path.insert security concern |
| P3-15 | LOW | Temp files may be readable by other users |
| P2-13 | MODERATE | No rate limiting or DoS protection |
| P3-14 | LOW | Error messages may leak internal details |

**Summary**: No P0 security findings. The main risks are CSV injection (if data is ever exported) and lack of rate limiting (potential DoS). The `sys.path.insert` concern is minor on single-user development machines but should be fixed before deployment on shared infrastructure.

---

## 20. Performance Risks

| ID | Severity | Finding |
|---|---|---|
| P1-1 | MAJOR | O(n²) duplicate detection within buckets |
| P2-15 | MODERATE | Unnecessary DataFrame copy in pipeline |
| P2-16 | MODERATE | pd.read_csv loads entire file into memory |

**Summary**: The O(n²) duplicate detection is the most significant performance risk. For files with >10,000 transactions of the same asset/quantity, the server will hang. This should be addressed before production deployment with large files.

---

## 21. Maintainability Risks

| ID | Severity | Finding |
|---|---|---|
| P3-5 | LOW | Module-level side effects in registry |
| P3-6 | LOW | No BaseAdapter validation on registration |
| P3-7 | LOW | Global mutable state not thread-safe |
| P3-8 | LOW | CommentEngine coupled to source_remark |
| P3-11 | LOW | Hardcoded "Binance Convert" in reason strings |
| P3-13 | LOW | No CORS headers |
| P2-9 | MODERATE | No delimiter configuration |
| P2-10 | MODERATE | No duplicate column handling |

**Summary**: The codebase is reasonably maintainable. The registry side effects and lack of BaseAdapter validation are minor issues. The detector and pipeline are well-structured. The main maintainability concern is the lack of delimiter configuration, which will cause user confusion with non-comma CSV formats.

---

## 22. Recommended Fixes

### Implementation Order for M019

| Priority | Fix | Effort | Impact |
|---|---|---|---|
| 1 | P1-1: Fix O(n²) duplicate detection | High | Prevents server hangs on large files |
| 2 | P2-12: Fix inconsistent /process error response | Low | Improves API reliability |
| 3 | P2-2: Add fee non-negative validation | Low | Prevents financial data corruption |
| 4 | P2-3: Add quantity positive validation | Low | Prevents financial data corruption |
| 5 | P2-1: Add price/quote_asset cross-field validation | Low | Improves data quality |
| 6 | P2-5: Document SWAP reconciliation boundary | Low | Clarifies Coinbase limitations |
| 7 | P2-7: Add CSV injection protection | Medium | Security hardening |
| 8 | P2-8: Add content-type validation | Low | Security hardening |
| 9 | P2-9: Add delimiter auto-detection | Medium | Usability improvement |
| 10 | P2-10: Reject duplicate column names | Low | Data quality |
| 11 | P3-5: Add registry reset for tests | Low | Test isolation |
| 12 | P3-6: Validate BaseAdapter on registration | Low | Defensive programming |

---

## Summary

**Current test count**: 252 passed, 0 failed
**Files inspected**: 18
**Files that would need modification for M019**: 
- `backend/reconciliation/duplicates.py` (P1-1)
- `backend/main.py` (P2-12, P2-8)
- `backend/models/transaction.py` (P2-1, P2-2, P2-3)
- `backend/ingestion/reader.py` (P2-7, P2-9, P2-10)
- `backend/adapters/registry.py` (P3-5, P3-6)
- `ARCHITECTURE_SPEC.md` (P2-5 documentation)

**No application source files were modified during this audit.**
