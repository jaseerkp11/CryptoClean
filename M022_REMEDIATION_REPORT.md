# M022 — Accounting Correctness Remediation Report

**Date**: 2026-08-31
**Baseline**: 325 tests passed, 0 failed
**Final**: 337 tests passed, 0 failed
**Status**: ACCEPTED

---

## 1. Baseline Test Count

**Before M022**: 325 tests passed, 0 failed

---

## 2. P0 Findings — Root Cause, Fix, and Tests

### P0-1 — Fee fabricates missing acquisition cost basis

**Root Cause**: `apply_acquisition_fee` in `backend/accounting/fees.py` executed `(cost_basis or Decimal("0")) + fee`, fabricating a cost basis from the fee alone when `cost_basis` was `None`.

**Fix**: Modified `apply_acquisition_fee` to only adjust `cost_basis` when it is not `None`. When `cost_basis` is `None` and `fee_asset == quote_asset`, the function now returns `cost_basis` unchanged and emits a `THIRD_ASSET_FEE` warning stating that the fee cannot be allocated because the acquisition cost basis is unknown.

**Tests Added**:
1. `test_quote_asset_fee_with_missing_cost_basis_does_not_fabricate`
2. `test_base_asset_fee_with_missing_cost_basis_does_not_fabricate`
3. `test_third_asset_fee_with_missing_cost_basis_does_not_fabricate`

---

### P0-2 — Fee creates negative fabricated disposal proceeds

**Root Cause**: `apply_disposal_fee` executed `(proceeds or Decimal("0")) - fee`, producing negative proceeds when `proceeds` was `None`.

**Fix**: Modified `apply_disposal_fee` to only adjust `proceeds` when it is not `None`. When `proceeds` is `None` and `fee_asset == quote_asset`, the function returns `proceeds` unchanged and emits a `THIRD_ASSET_FEE` warning.

**Tests Added**:
1. `test_quote_asset_fee_with_missing_proceeds_does_not_fabricate_negative`

---

### P0-3 — Swap acquisition cost basis ignores disposal proceeds

**Root Cause**: `_process_swap_pair` in `backend/accounting/swaps.py` resolved acquisition cost exclusively from the output transaction's `value`/`price`. When the output leg lacked valuation, the acquisition lot was created with `unit_cost = None` even though disposal proceeds were known.

**Fix**: Added fallback logic in `_process_swap_pair`: when `acquisition_cost` is `None` and `disposal_proceeds` is not `None`, use `disposal_proceeds` as the acquisition cost basis. If the output leg has a quote-asset fee, subtract it from the fallback cost basis.

**Tests Added**:
1. `test_swap_acquisition_uses_disposal_proceeds_when_output_leg_missing_value`
2. `test_swap_acquisition_uses_disposal_proceeds_minus_fee`

---

### P0-4 — Currency mismatch not validated before P&L

**Root Cause**: `_process_disposal` passed `proceeds_currency` as `cost_currency` to `select_lots`, and the engine computed `realized_pnl` without verifying that the lot's original cost currency matched the disposal's proceeds currency.

**Fix**:
1. Modified `FIFOMethod.select_lots` to record each lot's actual `cost_currency` in `LotConsumption` instead of using the disposal's `proceeds_currency`.
2. Added per-consumption currency validation in `_process_disposal`: if `cost_currency != proceeds_currency`, emit a `CURRENCY_MISMATCH` warning and set `realized_pnl = None` for that consumption.

**Tests Added**:
1. `test_currency_mismatch_produces_warning_and_null_pnl`

---

## 3. P1 Findings — Root Cause, Fix, and Tests

### P1-1 — Duplicate transactions double-count accounting

**Root Cause**: `DuplicateDetector` returned `unique_transaction_ids` that excluded ALL members of duplicate groups, including one legitimate copy. The pipeline passed the full transaction list to accounting, which processed every transaction unconditionally.

**Fix**:
1. Modified `DuplicateDetector.detect` in `backend/reconciliation/duplicates.py` to include one representative transaction ID from each duplicate group in `unique_transaction_ids`.
2. Added `unique_transaction_ids` parameter to `AccountingEngine.process`. The engine skips transactions whose IDs are not in the set AND skips duplicate transaction IDs encountered during processing.

**Tests Added**:
1. `test_duplicate_buy_does_not_double_count_lots`
2. `test_duplicate_sell_does_not_double_count_pnl`

---

### P1-2 / P1-5 — P&L aggregation ignores currency consistency / currency from first consumption only

**Root Cause**: `_aggregate_realized_pnl` took the currency from the first consumption and summed all `realized_pnl` values regardless of their individual currencies.

**Fix**: Modified `_aggregate_realized_pnl` to group consumptions by `pnl_currency` (falling back to `proceeds_currency`). Produces one `RealizedPnL` record per currency. Mixed-currency disposals now produce separate aggregates.

**Tests Added**:
1. `test_realized_pnl_aggregated_by_currency`

---

### P1-3 — Transfers don't preserve lot linkage

**Root Cause**: `process_transfer` created a `TRANSFER` event with no linkage to the lots being transferred. The receiving account had no audit trail back to the original acquisition lot.

**Fix**: Modified `process_transfer` to accept `lot_pool` and `all_lots`. For matched transfers, the function finds lots with matching asset and sufficient remaining quantity (FIFO order) and links their IDs to the `TRANSFER` event via `linked_lot_ids`.

**Tests Added**:
1. `test_matched_transfer_links_lots`

---

### P1-4 — Cross-exchange transfers can't be matched

**Root Cause**: `TransferReconciler._is_match` required `a.source == b.source`, preventing any cross-exchange transfer matching. The bucket key `(source, account)` further isolated legs by source.

**Fix**:
1. Added `tx_hash` field to `TransferLeg` model.
2. Modified `TransferReconciler._is_match` to allow cross-source matching when both legs have the same non-None `tx_hash` and timestamps are within tolerance.
3. Added a second pass in `TransferReconciler.reconcile` that compares legs across different sources when `tx_hash` matches.
4. Updated `BinanceTransferRules.extract_leg` to populate `tx_hash` from the canonical transaction.

**Tests Added**:
1. `test_cross_exchange_transfer_matched_with_tx_hash`

---

## 4. Files Created/Modified

### Modified Files
- `backend/accounting/fees.py` — P0-1, P0-2
- `backend/accounting/swaps.py` — P0-3
- `backend/accounting/methods.py` — P0-4 (use lot.cost_currency)
- `backend/accounting/engine.py` — P0-4, P1-1, P1-2/P1-5, P1-3
- `backend/accounting/transfers.py` — P1-3
- `backend/reconciliation/duplicates.py` — P1-1
- `backend/reconciliation/transfers.py` — P1-4
- `backend/reconciliation/binance_transfers.py` — P1-4
- `backend/processing/pipeline.py` — P1-1 (pass unique_transaction_ids)
- `backend/tests/test_accounting.py` — All P0/P1 tests

### No New Files Created

---

## 5. Architectural Decisions

1. **Fee handling with missing cost/proceeds**: The fee functions now preserve `None` values instead of fabricating numbers. This is a behavioral change that strictly prevents invalid financial values from entering the accounting pipeline.

2. **Swap valuation fallback**: Disposal proceeds are used as a fallback for acquisition cost basis only when the output leg lacks explicit valuation. This preserves economic continuity without double-counting.

3. **Currency validation at consumption level**: Currency mismatch is detected per `LotConsumption` rather than globally, allowing partial P&L calculation for matched-currency portions while nullifying mismatched portions.

4. **Duplicate filtering in engine**: The engine accepts `unique_transaction_ids` and deduplicates by transaction ID during processing. This keeps canonical results intact while preventing double-counting.

5. **Cross-exchange transfer matching**: Restricted to `tx_hash` matches only. This is the strongest deterministic evidence and avoids false positives from mere asset/quantity similarity.

---

## 6. Transfer Matching Rules

- **Intra-exchange**: Same source, same asset, equal quantity, opposite signed amounts, compatible accounts, timestamps within tolerance.
- **Cross-exchange**: Different sources allowed ONLY when `tx_hash` matches and timestamps are within tolerance.
- **Unmatched**: Emits `UNMATCHED_TRANSFER` warning. No fabricated lots or P&L.

---

## 7. Swap Valuation Rules

1. Acquisition cost = output transaction `value` or `price * quantity` if available.
2. Fallback = disposal proceeds if output leg lacks valuation.
3. If fallback is used and output leg has quote-asset fee, subtract fee from fallback.
4. If neither side has valuation, acquisition cost remains `None` with `MISSING_COST_BASIS` warning.
5. Never double-count value.

---

## 8. Fee Treatment Rules

| Scenario | Cost Basis Known | Proceeds Known | Behavior |
|---|---|---|---|
| Quote-asset fee on BUY | Yes | N/A | Add fee to cost basis |
| Quote-asset fee on BUY | No | N/A | Preserve None; emit warning |
| Quote-asset fee on SELL | N/A | Yes | Subtract fee from proceeds |
| Quote-asset fee on SELL | N/A | No | Preserve None; emit warning |
| Base-asset fee on BUY | Yes | N/A | Reduce quantity |
| Base-asset fee on SELL | N/A | Yes | Reduce disposal quantity |
| Third-asset fee | Any | Any | Warning only; no allocation |

---

## 9. Currency Consistency Rules

- Cost basis currency is derived from the acquisition transaction's `quote_asset`.
- Proceeds currency is derived from the disposal transaction's `quote_asset`.
- Before computing `realized_pnl`, verify `lot.cost_currency == proceeds_currency`.
- If mismatch: emit `CURRENCY_MISMATCH` warning, set `realized_pnl = None`.
- P&L aggregation groups by currency; produces one `RealizedPnL` per currency.
- No FX conversion is performed.

---

## 10. Duplicate Isolation Behavior

- `DuplicateDetector` returns `unique_transaction_ids` containing one representative per duplicate group plus all truly unique transactions.
- `AccountingEngine.process` accepts `unique_transaction_ids` and skips transactions not in the set.
- Within the processing loop, the engine tracks `processed_tx_ids` and skips subsequent transactions with the same ID.
- Canonical `ProcessingResult.transactions` retains ALL original transactions (no deletion).

---

## 11. Determinism Verification

- All IDs use SHA-256 of sorted deterministic inputs.
- FIFO lot selection sorts by `(acquired_timestamp, lot_id)`.
- Swap grouping sorts by timestamp then asset.
- P&L aggregation sorts by `(currency, from_timestamp)`.
- Duplicate filtering uses `set` membership, which is deterministic for identical inputs.
- Verified by existing `test_deterministic_result` and `test_fifo_identical_timestamps_deterministic`.

---

## 12. Canonical Immutability Verification

- `CanonicalTransaction` has `ConfigDict(frozen=True)`.
- Accounting engine never mutates input transactions.
- Verified by existing `test_canonical_transaction_not_mutated` and `test_canonical_transaction_not_mutated_by_swap`.

---

## 13. Final Test Count

**337 tests passed, 0 failed, 1 warning**

- Baseline: 325
- New P0/P1 regression tests: 12
- Total: 337

---

## 14. Remaining Risks

1. **Transfer cost basis preservation**: Matched transfers now link to source lots via `linked_lot_ids`, but the lot pool remains global. If a user transfers an asset and later sells it from a different account, the FIFO engine will consume the original lot (correct behavior), but the accounting event trail does not yet create a new lot on the destination side. This is consistent with the M020 spec but may need clarification for multi-account reporting.

2. **Cross-exchange transfer matching**: Currently requires matching `tx_hash`. If exchanges do not include transaction hashes in their exports, cross-exchange transfers will remain unmatched. This is a safe limitation but should be documented.

3. **Withdrawal classification**: Still treated as `NON_ACCOUNTING` per M020-A. The M020 spec §3.4 describes it as `DISPOSAL` with `proceeds=0`, but changing this would alter existing behavior. This should be addressed in a future milestone with explicit spec clarification.

---

## 15. M022 Verdict

**M022 ACCEPTED**

All P0 and P1 findings have been remediated. The accounting engine now:
- Never fabricates cost basis or proceeds from fees
- Validates currency compatibility before P&L calculation
- Falls back to disposal proceeds for swap acquisition valuation
- Filters duplicate transactions to prevent double-counting
- Aggregates P&L by currency
- Preserves lot linkage for matched transfers
- Supports cross-exchange transfer matching via tx_hash

The test suite passes with 337 tests, 0 failures.

---

## 16. Recommended Next Milestone

**M023 — Production Hardening & Missing-Spec Clarification**

Recommended focus areas:
1. Clarify and align withdrawal accounting behavior with M020 spec §3.4.
2. Implement per-account lot tracking if multi-account reporting is required.
3. Add integration tests for mixed Binance/Coinbase accounting runs.
4. Add stress tests for large datasets (10K+ transactions).
5. Document cross-exchange transfer matching limitations and required data fields.
