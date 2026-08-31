# M026 — Accounting P2 Hardening Remediation Report

**Date**: 2026-08-31  
**Baseline**: 343 tests passed, 0 failed  
**Final**: 361 tests passed, 0 failed  
**Status**: ACCEPTED

---

## 1. Executive Summary

M026 remediated all four P2 findings discovered by M025 adversarial audit. The fixes address currency mismatch validation bypass, excessive swap fee handling, cross-exchange duplicate grouping, and swap handler pairing limitations.

**Verdict: ACCEPTED**

All four P2 findings have been correctly remediated. The full test suite passes with 361 tests (343 baseline + 18 new regression tests). No existing behavior regressed.

---

## 2. Baseline

**Tests before**: 343 passed, 0 failed  
**Tests after**: 361 passed, 0 failed  
**Failures**: 0

---

## 3. P2-1 Currency Mismatch

### Root Cause

`backend/accounting/engine.py:380-386` — Currency mismatch validation required both `cost_currency` and `proceeds_currency` to be non-None before checking for mismatch. When `proceeds_currency` was None (e.g., disposal had value/price but no quote_asset), the validation was silently bypassed and PnL was computed without currency confirmation.

### Fix

Extended currency mismatch detection to cover:
- `cost_currency` known + `proceeds_currency` None → mismatch
- `cost_currency` None + `proceeds_currency` known → mismatch
- Both known + different → mismatch (existing behavior)
- Both None → no mismatch (both unknown)

### Tests

1. `test_currency_mismatch_usd_cost_usdt_proceeds`
2. `test_currency_mismatch_eur_cost_usd_proceeds`
3. `test_currency_mismatch_missing_proceeds_currency`
4. `test_currency_mismatch_missing_cost_currency`
5. `test_currency_matching_no_mismatch`
6. `test_currency_multiple_currencies_separate_aggregation`

### Result

All tests pass. Currency mismatch is now detected regardless of which currency is missing.

---

## 4. P2-2 Excessive Swap Fee

### Root Cause

`backend/accounting/swaps.py:136-140` — When swap acquisition cost basis fell back to disposal proceeds and the output leg had a base-asset fee exceeding the acquired quantity, the cost basis was set to None. This was inconsistent with `apply_acquisition_fee` which preserves cost basis and emits a warning.

### Fix

Preserved the fallback cost basis when base-asset fee exceeds quantity, with a THIRD_ASSET_FEE warning explaining the condition. This aligns swap fee handling with the existing fee policy.

### Tests

1. `test_swap_excessive_base_asset_fee_preserves_cost_basis`
2. `test_swap_base_asset_fee_equal_to_quantity`
3. `test_swap_normal_base_asset_fee`
4. `test_swap_third_asset_fee`

### Result

All tests pass. Excessive base-asset fees no longer nullify valid cost basis.

---

## 5. P2-3 Cross-Exchange Duplicate Grouping

### Root Cause

`backend/reconciliation/duplicates.py:97-99` — The duplicate detector treated identical `transaction_id` as an exact duplicate (score 100) regardless of source. Cross-exchange transactions with the same ID would be incorrectly grouped as duplicates.

### Fix

Made the `transaction_id` exact-duplicate check source-aware. Identical `transaction_id` now only produces score 100 when `source` also matches. Cross-exchange transactions with the same ID are not automatically duplicates but can still match via `tx_hash`.

### Tests

1. `test_same_source_same_transaction_id_is_duplicate`
2. `test_cross_exchange_same_transaction_id_not_automatic_duplicate`
3. `test_cross_exchange_same_tx_hash_may_match_via_transfer`
4. `test_same_source_same_tx_hash_is_duplicate`
5. `test_cross_exchange_different_values_not_duplicate`
6. `test_exact_duplicate_same_source_remains_duplicate`

### Transfer Regression Verification

Cross-exchange transfer matching remains functional. The `TransferReconciler._is_match` method matches cross-exchange transfers by `tx_hash` independently of duplicate detection. Verified by `test_cross_exchange_transfer_matched_with_tx_hash`.

### Result

All tests pass. Cross-exchange transactions with same ID are no longer automatically duplicates. Legitimate cross-exchange transfer matching remains intact.

---

## 6. P2-4 Swap Direct-Pair Limitation

### Root Cause

`backend/accounting/swaps.py:95-106` — Swap handler grouped transactions by timestamp and required even-sized groups. Odd-numbered groups were entirely marked unpaired, even when some transactions could be paired.

### Fix

Implemented greedy pairing within timestamp groups. Transactions are sorted by asset and paired (0,1), (2,3), etc. If odd number, the last transaction is marked unpaired. This maximizes the number of supported swap pairs.

### Tests

1. `test_swap_three_transactions_greedy_pairing`
2. `test_swap_four_transactions_two_pairs`

### Result

All tests pass. Greedy pairing maximizes supported swaps while clearly marking unsupported ones.

---

## 7. Regression Results

### M021 P0/P1 Findings

| Finding | Status |
|---------|--------|
| Fee fabrication when cost_basis is None | PASS |
| Fee creates negative proceeds | PASS |
| Swap acquisition ignores disposal proceeds | PASS |
| Currency mismatch not validated | PASS (enhanced by M026) |
| Duplicate double-counting | PASS |
| P&L aggregation ignores currency | PASS |
| Transfer cost basis preservation | PASS |
| Cross-exchange transfer matching | PASS |

### M022 Remediation

All M022 fixes verified PASS.

### M023 Cross-Asset FIFO

| Test | Status |
|------|--------|
| test_fifo_eth_disposal_does_not_consume_btc_lot | PASS |
| test_fifo_multi_asset_interleaved_partial | PASS |
| test_fifo_insufficient_inventory_one_asset_other_has_lots | PASS |
| test_fifo_multiple_lots_per_asset_mixed_timestamps | PASS |
| test_fifo_swap_transfer_cross_asset | PASS |
| test_fifo_duplicate_transactions_across_assets | PASS |

### M025 Adversarial Findings

All M025 P2 findings remediated. P3 findings remain for future milestones.

---

## 8. Files Modified

| File | Change |
|------|--------|
| `backend/accounting/engine.py` | P2-1: Extended currency mismatch detection |
| `backend/accounting/swaps.py` | P2-2: Preserve cost basis on excessive fee; P2-4: Greedy swap pairing |
| `backend/reconciliation/duplicates.py` | P2-3: Source-aware transaction_id matching |
| `backend/tests/test_accounting.py` | Added 12 regression tests |
| `backend/tests/test_duplicates.py` | Added 6 regression tests |
| `ARCHITECTURE_SPEC.md` | Updated with M026 documentation |

---

## 9. Architectural Impact

No architectural boundaries changed. All fixes are within existing modules:

- **Accounting core**: Enhanced currency validation and swap fee handling
- **Reconciliation**: Enhanced duplicate detection source scoping
- **Tests**: Added focused regression coverage

The Binance/Coinbase exchange scope remains unchanged. No new exchanges were added.

---

## 10. Remaining Risks

### P3 Findings (from M025, not remediated in M026)

1. **Empty asset strings accepted**: `AccountingEvent.asset` allows empty string
2. **Content type validation allows None/empty**: `_validate_content_type` returns without error
3. **FIFO tie-breaker uses lot_id hash**: Deterministic but arbitrary for identical timestamps

### Future Considerations

- Multi-hop/indirect swaps remain unsupported (documented limitation)
- Per-account lot tracking for multi-account reporting
- Withdrawal accounting alignment with M020 spec §3.4

---

## 11. Final Acceptance

**M026 ACCEPTED**

All four P2 findings have been correctly remediated:
- P2-1: Currency mismatch validation enhanced
- P2-2: Swap fee handling aligned with fee policy
- P2-3: Duplicate detection source-aware
- P2-4: Swap handler greedy pairing implemented

The full test suite passes with 361 tests, 0 failures. No existing behavior regressed.
