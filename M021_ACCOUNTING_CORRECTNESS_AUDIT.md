# M021 — Accounting Correctness & Production Audit

**Date**: 2026-08-31
**Baseline**: 325 tests passed, 0 failed
**Status**: AUDIT ONLY — no source files modified

---

## A. Executive Summary

**Overall Assessment: NOT ACCEPTED**

The CryptoClean accounting implementation demonstrates solid structural foundations: deterministic IDs, Decimal discipline, FIFO lot tracking, and a clean separation between canonical ingestion and accounting. However, this audit identified **4 P0 (critical)** and **7 P1 (major)** financial-correctness defects that can produce materially incorrect P&L, cost basis, or accounting events under realistic conditions.

The most severe issues are:
1. Fees can **fabricate** cost basis or proceeds when price/value is missing.
2. Swap acquisition cost basis is **disconnected** from disposal proceeds.
3. Currency mismatches are **never validated**, allowing cross-currency P&L arithmetic.
4. Duplicate transactions are **not deduplicated** before accounting, enabling double-counting.

These defects mean the system cannot yet "reliably transform real-world Binance/Coinbase transaction exports into deterministic, auditable, financially correct realized P&L" as required.

---

## B. System Under Audit

Components inspected:
- `backend/models/transaction.py` — canonical model
- `backend/accounting/` — models, engine, methods, fees, transfers, swaps, exceptions, configuration
- `backend/processing/` — pipeline, models, comments
- `backend/reconciliation/` — duplicates, transfers, binance_transfers, converts, binance_converts
- `backend/ingestion/` — reader, detector
- `backend/adapters/` — binance/spot_trade_history, binance/transaction_record, coinbase/transaction_record, base, registry
- `backend/main.py` — API endpoints
- `tests/test_accounting.py` — accounting unit tests
- `tests/test_processing.py` — integration tests
- `M020_ACCOUNTING_SPEC.md` — authoritative accounting spec
- `ARCHITECTURE_SPEC.md` — architecture reference

---

## C. Requirement Compliance Matrix

| Requirement | Implementation | Test Coverage | Correct? | Risk |
|---|---|---|---|---|
| FIFO lot ordering by timestamp + lot_id tie-break | `methods.py` | Yes | PASS | Low |
| Partial lot consumption | `methods.py`, `engine.py` | Yes | PASS | Low |
| Insufficient lots warning/error | `methods.py`, `engine.py` | Yes | PASS | Low |
| Quote-asset fee on BUY adds to cost | `fees.py`, `engine.py` | Yes | PARTIAL | **P0** |
| Quote-asset fee on SELL reduces proceeds | `fees.py`, `engine.py` | Yes | PARTIAL | **P0** |
| Base-asset fee on BUY reduces quantity | `fees.py`, `engine.py` | Yes | PASS | Low |
| Base-asset fee on SELL reduces quantity | `fees.py`, `engine.py` | Yes | PASS | Low |
| Third-asset fee warning | `fees.py` | Yes | PASS | Low |
| Missing fee asset warning | `fees.py` | Yes | PASS | Low |
| Transfer matched → no lots created | `transfers.py`, `engine.py` | Yes | PASS | Low |
| Transfer unmatched → warning | `transfers.py`, `engine.py` | Yes | PASS | Low |
| Swap disposal consumes FIFO lots | `swaps.py`, `methods.py` | Yes | PARTIAL | **P1** |
| Swap acquisition creates lot | `swaps.py` | Yes | PARTIAL | **P1** |
| Missing swap proceeds → warning | `swaps.py` | Yes | PASS | Low |
| Realized PnL aggregation | `engine.py` | Yes | PARTIAL | **P1** |
| Currency matching before P&L | Not implemented | No | **FAIL** | **P0** |
| Duplicate deduplication before accounting | Not implemented | No | **FAIL** | **P1** |
| Withdrawal as DISPOSAL per spec | `engine.py` | Yes | **FAIL** | **P2** |
| Deterministic IDs | All modules | Yes | PASS | Low |
| Decimal integrity | All modules | Yes | PASS | Low |
| Immutability | Models, engine | Yes | PASS | Low |
| API `/api/v1/account` | `main.py` | Yes | PASS | Low |
| API `/api/v1/process?accounting=true` | `main.py` | Yes | PASS | Low |

---

## D. Financial Correctness Findings

### D.1 [P0] Fee fabricates cost basis when price/value is missing

**File**: `backend/accounting/fees.py`
**Function**: `apply_acquisition_fee`
**Exact behavior**: When `cost_basis` is `None` (missing price/value) and `fee_asset == quote_asset`, the function executes:
```python
adjusted_cost = (cost_basis or Decimal("0")) + fee
```
This fabricates a cost basis equal to the fee amount. The accounting engine then records a lot with a non-null `unit_cost` derived from this fabricated value.

**Why it matters**: A user importing a BUY with no price but with a fee (e.g., a staking reward or airdrop with a fee) will see a fabricated cost basis. This is financially incorrect and violates the spec:
> The engine must NEVER invent a cost basis, proceeds, or market value.

**Reproduction**:
```python
tx = CanonicalTransaction(
    transaction_type=TransactionType.TRADE, side=Side.BUY,
    asset="BTC", quantity=Decimal("1"),
    price=None, value=None,
    fee=Decimal("10"), fee_asset="USDT", quote_asset="USDT"
)
engine = AccountingEngine()
result = engine.process([tx])
# result.lots[0].unit_cost == Decimal("10")  ← fabricated
```

**Expected behavior**: When cost_basis is unknown, fees should NOT fabricate a cost basis. The lot should be created with `unit_cost = None` and a `MISSING_COST_BASIS` warning. The fee should be recorded separately or ignored for cost basis calculation until the cost is known.

**Actual behavior**: Lot is created with `unit_cost = 10`, `total_cost = 10`, no `MISSING_COST_BASIS` warning.

---

### D.2 [P0] Fee fabricates negative proceeds when disposal value is missing

**File**: `backend/accounting/fees.py`
**Function**: `apply_disposal_fee`
**Exact behavior**: When `proceeds` is `None` and `fee_asset == quote_asset`:
```python
adjusted_proceeds = (proceeds or Decimal("0")) - fee
```
This produces `-fee`, a negative proceeds value.

**Why it matters**: A SELL with no price/value but with a fee will record negative proceeds, producing a massively incorrect (and sign-inverted) P&L.

**Reproduction**:
```python
tx_sell = CanonicalTransaction(
    transaction_type=TransactionType.TRADE, side=Side.SELL,
    asset="BTC", quantity=Decimal("1"),
    price=None, value=None,
    fee=Decimal("10"), fee_asset="USDT", quote_asset="USDT"
)
# After processing: event.proceeds = Decimal("-10")
```

**Expected behavior**: If proceeds are unknown, fees should not adjust them. The disposal event should record `proceeds = None` with a `MISSING_PROCEEDS` warning.

---

### D.3 [P0] Swap acquisition cost basis ignores disposal proceeds

**File**: `backend/accounting/swaps.py`
**Function**: `_process_swap_pair`
**Exact behavior**: The acquisition cost basis is resolved exclusively from the output transaction:
```python
acquisition_cost, cost_currency, cost_warnings = _resolve_cost_basis(output_tx)
```
The spec states:
> Acquisition cost = disposal proceeds minus fees, or explicit input value if available.

The implementation never uses disposal proceeds as a fallback for the incoming asset's cost basis.

**Why it matters**: If the output leg of a swap lacks explicit value/price (common in exchange exports), the acquisition lot is created with `unit_cost = None` even though the disposal proceeds are known. This breaks the economic link between the two legs of the swap.

**Reproduction**:
```python
tx_out = CanonicalTransaction(transaction_type=TransactionType.SWAP, asset="BTC", quantity=1, price=50000, value=50000)
tx_in = CanonicalTransaction(transaction_type=TransactionType.SWAP, asset="ETH", quantity=0.5, price=None, value=None)
# Result: disposal has proceeds=50000, acquisition has unit_cost=None
```

**Expected behavior**: If `output_tx` lacks value/price, use `disposal_proceeds` (minus fees) as the acquisition cost basis.

---

### D.4 [P0] Currency mismatch not validated before P&L calculation

**File**: `backend/accounting/engine.py`
**Function**: `_aggregate_realized_pnl`, `_process_disposal`
**Exact behavior**: The engine computes `realized_pnl = lot_proceeds - cost_allocated` without verifying that `cost_currency == proceeds_currency`. The `LotConsumption` records `cost_currency` from the disposal transaction's `quote_asset` (via the `cost_currency` parameter passed to `select_lots`), not from the lot's actual `cost_currency`.

**Why it matters**: A user could have:
- BUY BTC with USDT cost basis
- SELL BTC with USD proceeds
The engine would compute `realized_pnl = USD_proceeds - USDT_cost`, a numerically valid but economically meaningless value. The spec explicitly states:
> Matching currencies required; FX normalization deferred.

**Reproduction**:
```python
tx_buy = CanonicalTransaction(..., quote_asset="USDT", price=50000, value=50000)
tx_sell = CanonicalTransaction(..., quote_asset="USD", price=50000, value=50000)
# P&L computed as 50000 USD - 50000 USDT = 0 (numerically valid, semantically wrong)
```

**Expected behavior**: If `lot.cost_currency != proceeds_currency`, the engine should emit a `CURRENCY_MISMATCH` warning and set `realized_pnl = None` for that consumption.

---

### D.5 [P1] Duplicate transactions produce double lots and double P&L

**File**: `backend/reconciliation/duplicates.py`, `backend/accounting/engine.py`
**Exact behavior**: `DuplicateDetector` identifies duplicate groups but returns `unique_transaction_ids` as an **informational** field. The pipeline passes the full `transactions` list (including all duplicates) to `AccountingEngine`. Accounting processes every transaction unconditionally.

**Why it matters**: A user who imports the same CSV twice, or who has identical trades from different sources, will see:
- Two acquisition lots for the same BUY
- Two disposal events for the same SELL
- Double consumption of lots
- Double P&L
- Potential negative remaining quantities if disposals exceed available lots after double-counting

**Reproduction**:
```python
tx1 = _tx("tx-a", side=Side.BUY, ...)
tx2 = _tx("tx-a", side=Side.BUY, ...)  # identical transaction_id
engine = AccountingEngine()
result = engine.process([tx1, tx2])
# len(result.lots) == 2  ← two lots for one economic event
```

**Expected behavior**: Accounting should either:
(a) Accept only `unique_transaction_ids` from `DuplicateResult`, or
(b) Accept a deduplicated transaction list from the caller, or
(c) Emit a clear error when duplicate transactions would distort accounting.

---

### D.6 [P1] Realized PnL aggregation ignores currency consistency

**File**: `backend/accounting/engine.py`
**Function**: `_aggregate_realized_pnl`
**Exact behavior**: When multiple disposals exist, the aggregation takes `currency` from the **first** consumption's `pnl_currency` or `proceeds_currency` and sums all `realized_pnl` values regardless of their individual currencies.

**Why it matters**: If a user trades BTC/USDT (P&L in USDT) and ETH/USD (P&L in USD) in the same run, the aggregated `RealizedPnL` will record a single currency (the first one encountered) and sum incompatible values.

**Expected behavior**: Group consumptions by currency before aggregation. Produce one `RealizedPnL` per currency, or emit a `CURRENCY_MISMATCH` warning if mixed currencies are detected.

---

### D.7 [P1] Transfers do not preserve cost basis across accounts

**File**: `backend/accounting/transfers.py`, `backend/reconciliation/transfers.py`
**Exact behavior**: A matched transfer creates only a `TRANSFER` accounting event. No lot is created or consumed. The receiving account has no record of the transferred asset or its cost basis.

**Why it matters**: If a user transfers BTC from Spot to Futures and later sells it from Futures, the accounting engine has no link between the Futures sale and the original Spot acquisition lot. The sale will find no available lots, producing `INSUFFICIENT_LOTS` and zero P&L.

**Reproduction**:
1. BUY 1 BTC @ $50,000 (Spot) → creates lot A
2. TRANSFER 1 BTC (Spot → Futures) → creates TRANSFER event only
3. SELL 1 BTC (Futures) → no lot available; INSUFFICIENT_LOTS error

**Expected behavior**: Matched transfers should preserve lot linkage. The receiving account should inherit the original lot's cost basis. The current architecture has no mechanism for this.

---

### D.8 [P1] Cross-exchange transfers cannot be matched

**File**: `backend/reconciliation/transfers.py`
**Function**: `_is_match`
**Exact behavior**: The transfer reconciler requires `a.source == b.source`. Binance and Coinbase transactions can never match.

**Why it matters**: A user moving funds between exchanges sees two independent events (withdrawal from Binance, deposit to Coinbase) with no accounting linkage. The deposit creates a new lot with potentially unknown cost basis, while the withdrawal produces no disposal event.

**Expected behavior**: Document this limitation clearly. Cross-exchange transfer matching requires additional heuristics (e.g., matching by amount, asset, and timestamp proximity) that are not currently implemented.

---

### D.9 [P2] Withdrawal treated as NON_ACCOUNTING instead of DISPOSAL

**File**: `backend/accounting/engine.py`
**Function**: `_process_withdrawal`
**Exact behavior**: Withdrawals create `NON_ACCOUNTING` events with `WITHDRAWAL_NO_PROCEEDS` warning.

**Spec requirement** (M020_ACCOUNTING_SPEC.md §3.4):
> Creates an `AccountingEvent` of type `DISPOSAL`.
> Withdrawal is treated as a disposal at `proceeds = 0`.

**Why it matters**: Withdrawals are invisible to FIFO lot consumption. A user who deposits and later withdraws the same asset will accumulate infinite lots with no disposals.

---

### D.10 [P2] Swap acquisition cost basis does not fall back to disposal proceeds

**File**: `backend/accounting/swaps.py`
**Function**: `_process_swap_pair`
**Exact behavior**: If the output transaction lacks price/value, `_resolve_cost_basis(output_tx)` returns `None` and emits `MISSING_COST_BASIS`. The disposal proceeds are available but ignored.

**Spec requirement** (§3.6):
> Acquisition cost = disposal proceeds minus fees, or explicit input value if available.

**Why it matters**: Many exchange exports provide explicit value only for the outgoing leg of a convert. The incoming leg may lack valuation, causing the acquisition lot to have `unit_cost = None` even though the economic cost is known.

---

### D.11 [P2] Binance Spot Trade History does not populate fee_value

**File**: `backend/adapters/binance/spot_trade_history.py`
**Function**: `adapt`
**Exact behavior**: The adapter sets `fee` and `fee_asset` but never computes `fee_value` (fee denominated in quote asset).

**Why it matters**: Downstream consumers (accounting, reporting) expecting `fee_value` for P&L calculations will find it `None`. The canonical model supports `fee_value` but the adapter does not populate it.

---

### D.12 [P2] Processing summary swap counts diverge from accounting summary

**File**: `backend/processing/pipeline.py`
**Function**: `_build_summary`
**Exact behavior**: The pipeline summary counts `TransactionType.SWAP` as `swaps`. Binance Convert transactions are `TransactionType.UNKNOWN`, so they appear as `unknown_transactions`. After accounting processes them, they become SWAP events.

**Why it matters**: The pre-accounting summary and post-accounting summary report different counts for the same data. Users consulting `ProcessingResult.summary` see 0 swaps and N unknown transactions, while `AccountingResult.summary` shows N swap events.

---

### D.13 [P2] Fee + missing cost basis produces fabricated unit cost

**File**: `backend/accounting/engine.py`
**Function**: `_process_acquisition`
**Exact behavior**: When `adjusted_cost_basis` is fabricated by `apply_acquisition_fee` (see D.1), `unit_cost` is computed as:
```python
unit_cost = adjusted_cost_basis / original_quantity
```
If `original_quantity` is the gross quantity (before base-asset fee reduction), the unit cost is correct for the adjusted cost. But if `cost_basis` was fabricated from fee alone, the unit cost is purely fabricated.

---

### D.14 [P2] No test coverage for duplicate-accounting interaction

**File**: `tests/test_accounting.py`
**Exact behavior**: No test verifies what happens when duplicate transactions are passed to `AccountingEngine`.

**Why it matters**: Finding D.5 is untested. A regression could silently reintroduce double-counting.

---

### D.15 [P2] No test coverage for cross-exchange accounting

**File**: `tests/test_accounting.py`
**Exact behavior**: All accounting tests use `Source.BINANCE`. No test mixes Binance and Coinbase transactions.

**Why it matters**: Cross-exchange lot pooling, currency handling, and duplicate behavior are unverified.

---

## E. FIFO Audit

### Scenario A
BUY 1 BTC @ 10,000
BUY 1 BTC @ 20,000
SELL 1 BTC @ 15,000

**Expected**: FIFO cost = 10,000; P&L = 5,000
**Actual**: PASS. Lot 1 fully consumed, cost_allocated = 10,000, realized_pnl = 5,000.

### Scenario B
BUY 1 BTC @ 10,000
BUY 1 BTC @ 20,000
SELL 1.5 BTC @ 30,000

**Expected**: Lot 1 fully consumed (cost 10,000), Lot 2 partially consumed 0.5 (cost 10,000), total cost = 20,000; proceeds = 45,000; P&L = 25,000
**Actual**: PASS. Proportional proceeds allocation is mathematically correct.

### Scenario C
BUY 0.333333333333 BTC
SELL 0.111111111111 BTC

**Expected**: remaining = 0.222222222222
**Actual**: PASS. Decimal precision preserved.

### Scenario D
Two acquisitions with identical timestamps.

**Expected**: Deterministic ordering by lot_id tie-breaker
**Actual**: PASS. `test_fifo_identical_timestamps_deterministic` verifies this.

### FIFO Conclusion
The FIFO implementation is **correct** for well-formed, non-duplicate, single-currency inputs. The defects are in the surrounding fee, swap, and duplicate handling, not in the core lot selection algorithm.

---

## F. Fee Audit

### Quote-asset fee on BUY
**Correctness**: PASS when cost_basis is known.
**Defect**: **P0** — fabricates cost basis when cost_basis is None (Finding D.1).

### Quote-asset fee on SELL
**Correctness**: PASS when proceeds are known.
**Defect**: **P0** — produces negative proceeds when proceeds are None (Finding D.2).

### Base-asset fee on BUY
**Correctness**: PASS. Quantity is reduced, unit_cost remains based on gross quantity.

### Base-asset fee on SELL
**Correctness**: PASS. Disposal quantity is reduced, proceeds allocated to reduced quantity.

### Third-asset fee
**Correctness**: PASS. Warning emitted, no fabricated allocation.

### Missing fee asset
**Correctness**: PASS. Warning emitted.

### Conclusion
Fee logic is correct **only when the underlying cost basis or proceeds are known**. When missing, the fee handling fabricates financial values, which is a critical defect.

---

## G. Transfer Audit

### Matched internal transfer (same exchange)
**Correctness**: PARTIAL. Creates TRANSFER event, no lots created/consumed.
**Defect**: **P1** — cost basis not preserved across accounts (Finding D.7). The receiving side cannot trace back to the original lot.

### Unmatched transfer
**Correctness**: PASS. Warning emitted, no fabricated lots or P&L.

### Cross-exchange transfer
**Correctness**: PARTIAL. Not matched by design.
**Defect**: **P1** — documented limitation but no user-visible warning that cross-exchange transfers will appear as independent deposit/withdrawal events (Finding D.8).

---

## H. Swap Audit

### Canonical SWAP transactions
**Correctness**: PARTIAL. Disposal leg correctly consumes FIFO lots. Acquisition leg creates lot.
**Defects**:
- **P1**: Acquisition cost basis does not fall back to disposal proceeds (Finding D.10)
- **P1**: Swap P&L is correct only when both legs have explicit valuation

### Binance Convert (UNKNOWN → ConvertFinding)
**Correctness**: PARTIAL. Accounting engine correctly identifies matched convert pairs and processes them as swaps.
**Defect**: **P2** — processing summary counts these as `unknown_transactions`, not `swaps` (Finding D.12).

---

## I. P&L Audit

### Formula verification
For each `LotConsumption`:
```
realized_pnl = lot_proceeds - cost_allocated
```
where `lot_proceeds = (disposal_proceeds / disposal_quantity) * consumed`.

This is **mathematically correct** for proportional allocation.

### Defects
- **P0**: Currency mismatch not validated (Finding D.4)
- **P1**: Aggregation ignores currency consistency (Finding D.6)
- **P0**: Fee/proceeds fabrication can produce invalid P&L (Findings D.1, D.2)

### Conclusion
The P&L formula is correct in isolation. The defects are in the **inputs** to the formula (fabricated proceeds/cost) and the **missing currency guard**.

---

## J. Multi-Currency Audit

### Currency tracking
- `cost_currency` is derived from `quote_asset` at acquisition time.
- `proceeds_currency` is derived from `quote_asset` at disposal time.
- `LotConsumption.cost_currency` is set to the disposal's `proceeds_currency`, **not** the lot's original `cost_currency`.

### Defect
**P0**: No validation that `cost_currency == proceeds_currency` before computing P&L (Finding D.4).

### Additional issue
If a lot is acquired with USDT and later disposed with USD proceeds, the `LotConsumption` records `cost_currency="USD"` (from the disposal), masking the original USDT cost. This makes post-hoc currency auditing impossible.

---

## K. Duplicate Interaction Audit

### Architecture claim
> Reconciliation must never delete transactions.

### Actual behavior
`DuplicateDetector` returns `unique_transaction_ids` but the pipeline ignores it. All transactions, including exact duplicates, are passed to accounting.

### Defect
**P1**: Accounting processes all transactions unconditionally, enabling double-counting of lots and P&L (Finding D.5).

### Risk assessment
This is a **high-severity** defect because:
1. Re-importing the same CSV is a common user action.
2. The duplicate detector already identifies the duplicates; the fix is to filter the transaction list.
3. The current behavior is silently incorrect — no warning is emitted when duplicates are processed by accounting.

---

## L. Determinism Audit

### ID generation
- Event IDs: `sha256(sorted([tx_id, event_type]))` — deterministic.
- Lot IDs: `sha256(sorted([tx_id, asset, quantity, timestamp]))` — deterministic.
- Consumption IDs: `sha256(sorted([lot_id, disposal_tx_id, quantity]))` — deterministic.
- PnL IDs: `sha256(sorted([consumption_ids, currency, from_ts, to_ts]))` — deterministic.

### Sorting
- FIFO lots sorted by `(acquired_timestamp, lot_id)` — deterministic.
- Swap groups sorted by timestamp, then by asset — deterministic.
- PnL aggregation sorts timestamps, consumption IDs, lot IDs, event IDs — deterministic.

### Ordering sensitivity
- Accounting processes transactions in input order.
- For FIFO disposals, lot selection depends on timestamp, not input order.
- Warning/error lists preserve insertion order, which is deterministic given deterministic input processing.

### Conclusion
**PASS**. The implementation is deterministic for identical input lists. The only caveat is that **duplicate transactions in different orders could produce different P&L aggregations** if the duplicate set includes both buys and sells in varying sequences, but this is a consequence of the duplicate-handling defect (D.5), not a fundamental non-determinism.

---

## M. API Audit

### `/api/v1/account`
- Accepts file + timezone
- Runs full pipeline with `AccountingConfiguration()`
- Returns `ProcessingResult` with `accounting_result`
- Error handling: 400 for missing timezone, 207 for partial errors, 500 for exceptions
- Decimal serialization: Pydantic `model_dump(mode="json")` serializes Decimal to string — **PASS**

### `/api/v1/process?accounting=true`
- Same as above but accounting is opt-in
- **PASS**

### Issues
- **P2**: API returns 207 Multi-Status when accounting errors occur but transactions were processed. This is unusual but intentional.
- **P3**: `_validate_content_type` allows `None` content-type (no error raised).
- **P3**: Accounting configuration is not user-configurable via API; defaults are always used.

---

## N. Mixed Exchange Audit

### Current behavior
- Binance and Coinbase transactions can coexist in a single `AccountingEngine.process()` call.
- Lot pools are global — a Binance BUY and Coinbase BUY of the same asset share the same lot pool.
- FIFO ordering is by timestamp across all sources.

### Potential issue
If both exchanges report the same economic event (e.g., a transfer represented as a Binance withdrawal and a Coinbase deposit), accounting will see:
1. Binance WITHDRAWAL → NON_ACCOUNTING event (no lot consumption)
2. Coinbase DEPOSIT → ACQUISITION event (new lot created with potentially different cost basis)

This is **not financially correct** — the economic cost basis is lost. However, this is a known limitation of the current architecture.

### Duplicate risk
If the same trade appears in both Binance and Coinbase exports (unlikely but possible for transfer-like events), the transaction IDs will differ, so the duplicate detector will not flag them. Accounting will process both, creating two lots for one economic event.

---

## O. Test Coverage Gaps

The following tests should be added in the next implementation milestone:

1. **Duplicate-accounting interaction**: Pass identical BUY/SELL pairs and verify no double lots or double P&L.
2. **Cross-exchange accounting**: Mix Binance and Coinbase transactions and verify FIFO ordering, currency handling, and P&L.
3. **Currency mismatch**: BUY with USDT cost, SELL with USD proceeds → verify `CURRENCY_MISMATCH` warning and `realized_pnl = None`.
4. **Fee + missing cost basis**: Verify no fabricated cost basis when fee exists but price/value is missing.
5. **Fee + missing proceeds**: Verify no negative proceeds when fee exists but price/value is missing.
6. **Swap acquisition from disposal proceeds**: Verify acquisition lot uses disposal proceeds when output leg lacks valuation.
7. **Transfer cost basis preservation**: Verify that a matched transfer preserves lot linkage for future disposals.
8. **Cross-exchange transfer limitation**: Verify and document that Binance→Coinbase transfers are not matched.
9. **Withdrawal as disposal**: Verify per spec that withdrawals create DISPOSAL events with proceeds=0.
10. **Realized PnL multi-currency aggregation**: Verify one `RealizedPnL` per currency.
11. **Processing vs accounting summary consistency**: Verify swap counts align when Binance Convert is present.
12. **Fee value computation**: Verify `fee_value` is populated in Spot Trade History adapter when `fee_asset == quote_asset`.

---

## P. Performance Findings

No code changes were made, but the following bottlenecks were identified:

1. **FIFO selection**: O(n log n) per disposal due to sorting. For 100,000 disposals against 100,000 lots, this is O(n² log n). Acceptable for M020 but needs optimization for production scale.
2. **Duplicate detection**: O(n²) within fingerprint buckets. The `max_fingerprint_bucket_size` parameter caps worst case but large uniform datasets could still be slow.
3. **P&L aggregation**: O(c) where c = number of consumptions. Currently acceptable.
4. **Decimal operations**: All financial math uses Decimal, which is slower than float but necessary for precision. No premature quantization observed.

---

## Q. Security / Privacy Findings

### PASS
- User IDs are stripped from Binance Transaction Record metadata (`metadata.pop("User ID", None)`).
- Sensitive key patterns are rejected by `metadata_no_secrets` validator.
- No API keys, secrets, or private keys are found in any output paths.
- No local filesystem paths are exposed in API responses.
- No stack traces are returned to API clients (generic 500 error).

### Minor concern
- **P3**: Temporary CSV files are written to the system temp directory. The cleanup logic catches `OSError` silently, which could leave files behind if deletion fails. Not a security issue but a minor hygiene concern.

---

## R. Specification Drift

| Spec Requirement | Implementation | Status |
|---|---|---|
| Withdrawal creates DISPOSAL event with proceeds=0 | Creates NON_ACCOUNTING event | **DRIFT** |
| Swap acquisition cost = disposal proceeds minus fees | Uses output transaction value/price only | **DRIFT** |
| Currency matching required before P&L | Not implemented | **MISSING** |
| Duplicate transactions should not distort accounting | All transactions passed to accounting | **MISSING** |
| Transfer preserves lot linkage | No lot linkage mechanism | **DRIFT** |

---

## S. Recommended Fix Order

### Phase 1 — Critical (P0)
1. **Fix fee fabrication**: In `apply_acquisition_fee` and `apply_disposal_fee`, do not adjust cost basis or proceeds when the underlying value is `None`. Emit warnings instead.
2. **Add currency validation**: In `_process_disposal` and `_aggregate_realized_pnl`, verify `cost_currency == proceeds_currency`. Emit `CURRENCY_MISMATCH` warning and set `realized_pnl = None` when mismatched.
3. **Fix swap acquisition cost basis**: In `_process_swap_pair`, fall back to `disposal_proceeds` (minus fees) when `output_tx` lacks value/price.

### Phase 2 — Major (P1)
4. **Implement duplicate filtering**: Modify `AccountingEngine.process()` to accept a `transaction_ids_to_exclude` set, or filter transactions in the pipeline before calling accounting.
5. **Fix P&L currency aggregation**: Group `RealizedPnL` by currency instead of producing a single aggregate.
6. **Design transfer cost basis preservation**: Define a mechanism for matched transfers to carry lot IDs to the receiving account.

### Phase 3 — Moderate (P2)
7. **Align withdrawal with spec**: Change `_process_withdrawal` to create `DISPOSAL` events with `proceeds=0`.
8. **Populate fee_value in Spot Trade History adapter**: Compute `fee_value = fee * price` when `fee_asset == quote_asset`.
9. **Fix processing/accounting summary divergence**: Ensure Binance Convert events are counted consistently.
10. **Add missing tests** (see Section O).

---

## T. Final Verdict

**M021 NOT ACCEPTED**

The implementation contains P0 financial-correctness defects that can produce fabricated cost basis, fabricated proceeds, and cross-currency P&L. These are not edge cases — they occur in realistic scenarios such as fee-bearing acquisitions without explicit pricing, and swaps where only one leg has valuation.

The architecture is sound, the FIFO core is correct, and the test suite is comprehensive for the happy path. However, the missing-data and cross-currency guards are insufficient for production financial use.

**Next steps**: Implement Phase 1 (P0) fixes, then re-audit before considering production readiness.
