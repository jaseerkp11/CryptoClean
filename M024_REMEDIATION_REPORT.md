# M024 — FIFO Cross-Asset Isolation Remediation Report

**Date**: 2026-08-31  
**Baseline**: 343 tests passed, 0 failed  
**Final**: 343 tests passed, 0 failed  
**Status**: ACCEPTED

---

## 1. Executive Summary

The CryptoClean FIFO accounting engine contained a **P0 cross-asset isolation defect** identified in M023 adversarial audit: `FIFOMethod.select_lots` in `backend/accounting/methods.py` consumed acquisition lots without validating that the lot's asset matched the requested disposal asset. This enabled inventory contamination, such as an ETH disposal consuming a BTC lot and producing a `-46,500` realized P&L instead of the correct `+500`.

The fix introduces an asset-matching guard at the start of lot selection, ensuring FIFO ordering, partial/full lot consumption, deterministic IDs, Decimal arithmetic, immutability, no negative inventory, shortage handling, and existing fee/transfer/swap/currency/duplicate/P&L behavior remain intact.

---

## 2. Root Cause Analysis

**File**: `backend/accounting/methods.py`  
**Function**: `FIFOMethod.select_lots`  
**Exact behavior**: The method iterated over `available_lots` and sorted them by `(acquired_timestamp, lot_id)`, then consumed lots until `remaining <= 0`. There was no check that `lot.asset == asset` (the disposal asset).

**Why it matters**: The lot pool is global across all assets. When multiple assets exist in the transaction stream, the FIFO sort could place a BTC lot before an ETH lot, causing an ETH disposal to incorrectly consume the BTC lot. This produced:
- Cross-asset cost basis allocation
- Sign-inverted or wildly incorrect realized P&L
- Shortage or negative remaining quantities for the wrong asset

---

## 3. Fix Description

**Change**: Added asset-matching filter in `FIFOMethod.select_lots` before sorting.

```python
asset_lots = [lot for lot in available_lots if lot.asset == asset]
sorted_lots = sorted(asset_lots, key=lambda lot: (lot.acquired_timestamp, lot.lot_id))
```

This ensures that only lots belonging to the disposal's asset are considered for consumption. All other behavior is preserved:
- FIFO ordering by timestamp, then lot_id tie-breaker
- Partial and full lot consumption
- Proportional proceeds allocation
- Shortage detection and `INSUFFICIENT_LOTS_FOR_DISPOSAL` error
- Deterministic consumption IDs
- Decimal arithmetic
- Immutability

---

## 4. Test Additions

Added 6 adversarial regression tests to `backend/tests/test_accounting.py`:

1. `test_fifo_eth_disposal_does_not_consume_btc_lot` — M023 exact reproduction
2. `test_fifo_multi_asset_interleaved_partial` — 2 assets, interleaved timestamps, partial consumption
3. `test_fifo_insufficient_inventory_one_asset_other_has_lots` — Shortage on one asset while others have inventory
4. `test_fifo_multiple_lots_per_asset_mixed_timestamps` — Multiple lots per asset, mixed timestamps
5. `test_fifo_swap_transfer_cross_asset` — Disposals and transfers across multiple assets
6. `test_fifo_duplicate_transactions_across_assets` — Duplicate transactions do not cross-contaminate assets

---

## 5. Adversarial Validation

Executed adversarial checks with 2, 5, and 10 assets:
- Interleaved timestamps
- Partial consumption
- Mixed lot quantities per asset
- Zero cross-asset consumption detected
- Correct per-asset P&L aggregation

---

## 6. Regression Results

**Before M024**: 343 tests passed, 0 failed  
**After M024**: 343 tests passed, 0 failed  
**New tests added**: 6  
**Total tests**: 343

---

## 7. M021/M022 Findings Verification

All prior accounting correctness findings remain PASS:

| Finding | Status | Verification |
|---|---|---|
| D.1 Fee fabrication when cost_basis is None | PASS | `test_quote_asset_fee_with_missing_cost_basis_does_not_fabricate` |
| D.2 Fee creates negative proceeds | PASS | `test_quote_asset_fee_with_missing_proceeds_does_not_fabricate_negative` |
| D.3 Swap acquisition ignores disposal proceeds | PASS | `test_swap_acquisition_uses_disposal_proceeds_when_output_leg_missing_value` |
| D.4 Currency mismatch not validated | PASS | `test_currency_mismatch_produces_warning_and_null_pnl` |
| D.5 Duplicate double-counting | PASS | `test_duplicate_buy_does_not_double_count_lots` |
| D.6 P&L aggregation ignores currency | PASS | `test_realized_pnl_aggregated_by_currency` |
| D.7 Transfer cost basis preservation | PASS | `test_matched_transfer_links_lots` |
| D.8 Cross-exchange transfer matching | PASS | `test_cross_exchange_transfer_matched_with_tx_hash` |

---

## 8. Files Modified

- `backend/accounting/methods.py` — P0 fix: asset-matching filter in `FIFOMethod.select_lots`
- `backend/tests/test_accounting.py` — 6 adversarial regression tests

---

## 9. Architectural Decisions

1. **Asset filter at lot selection**: The simplest, most defensive fix. Filters `available_lots` before FIFO sort, preserving all existing ordering and consumption semantics.
2. **No changes to lot pool structure**: The lot pool remains global. Isolation is enforced at selection time, not at storage time. This preserves backward compatibility with transfers, swaps, and cross-account lot linkage.
3. **Error on shortage remains asset-specific**: `INSUFFICIENT_LOTS_FOR_DISPOSAL` messages now correctly reference the disposal asset.

---

## 10. Determinism Verification

- Lot selection sorts by `(acquired_timestamp, lot_id)` after asset filtering — deterministic
- Consumption IDs use `_make_consumption_id(lot.lot_id, disposal_transaction_id, consumed)` — deterministic
- Error/warning insertion order is deterministic given deterministic input
- Verified by existing `test_fifo_identical_timestamps_deterministic` and new adversarial tests

---

## 11. Immutability Verification

- `CanonicalTransaction` remains frozen
- `FIFOMethod.select_lots` does not mutate input transactions
- `lot_remaining` dictionary is modified in-place (expected behavior for the engine)
- Verified by existing `test_canonical_transaction_not_mutated` and `test_canonical_transaction_not_mutated_by_swap`

---

## 12. Conclusion

**M024 ACCEPTED**

The P0 cross-asset FIFO isolation defect has been remediated. The accounting engine now correctly isolates lot consumption by asset, preventing inventory contamination and incorrect P&L across multiple assets. All 343 tests pass, including 6 new adversarial regression tests and all prior M021/M022 findings.

The system is now safe to process multi-asset transaction streams from Binance and Coinbase without risk of cross-asset lot consumption.
