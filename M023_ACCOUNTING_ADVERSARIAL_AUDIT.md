# M023 — Accounting Adversarial Correctness Audit

**Date**: 2026-08-31
**Baseline**: 337 tests passed, 0 failed
**Status**: AUDIT ONLY — no production source files modified

---

## 1. Executive Summary

This adversarial audit of the CryptoClean accounting system after M022 remediation identified **1 new P0 (critical)** financial-correctness defect that was not discovered in M021 or M022.

The defect allows the FIFO cost-basis engine to consume acquisition lots for a **different asset** than the one being disposed. This produces materially incorrect cost basis, realized P&L, and inventory tracking.

All M022 P0 and P1 remediations were verified as **PASS** against the original M021 findings. However, the new P0 finding means the system cannot yet be accepted for production use.

**Overall Assessment: NOT ACCEPTED**

---

## 2. Verdict

**NOT ACCEPTED**

The accounting engine contains a P0 cross-asset lot consumption bug that can produce financially incorrect results under realistic multi-asset trading scenarios.

---

## 3. Baseline Test Result

**Before M023 audit**: 337 tests passed, 0 failed

**During M023 audit**: 38 temporary adversarial audit tests were added. Of these:
- 36 passed (confirming correct behavior in covered scenarios)
- 2 failed (exposing the P0 cross-asset bug and an incorrect test expectation)

The 2 failures were in the temporary audit test file only. The permanent test suite remains at 337 passed, 0 failed.

---

## 4. P0 Findings

### P0-1 — FIFO lot selection does not filter by asset

**File**: `backend/accounting/methods.py`
**Function**: `FIFOMethod.select_lots`
**Exact behavior**: The FIFO method receives `available_lots: List[AcquisitionLot]` containing lots for **all assets**. It iterates over all lots and selects the earliest ones by `(acquired_timestamp, lot_id)` **without checking whether `lot.asset == asset`** (the disposal asset).

**Why it matters**: When a portfolio contains multiple assets (e.g., BTC and ETH), selling one asset can consume lots from a different asset. This produces:
- Wrong cost basis (cost from unrelated asset)
- Wrong realized P&L (can be massively positive or negative)
- Corrupted inventory tracking (wrong asset's remaining quantity goes to 0)
- Complete loss of auditability

**Reproduction scenario**:
```python
# Buy BTC @ $50,000
tx_btc = CanonicalTransaction(transaction_id="tx-0", asset="BTC", side=Side.BUY, 
                               quantity=Decimal("1"), price=Decimal("50000"), value=Decimal("50000"),
                               timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc))
# Buy ETH @ $3,000
tx_eth = CanonicalTransaction(transaction_id="tx-1", asset="ETH", side=Side.BUY,
                               quantity=Decimal("1"), price=Decimal("3000"), value=Decimal("3000"),
                               timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc))
# Sell ETH @ $3,500
tx_sell_eth = CanonicalTransaction(transaction_id="tx-2", asset="ETH", side=Side.SELL,
                                    quantity=Decimal("1"), price=Decimal("3500"), value=Decimal("3500"),
                                    timestamp=datetime(2024, 1, 3, tzinfo=timezone.utc))

engine = AccountingEngine()
result = engine.process([tx_btc, tx_eth, tx_sell_eth])

# Expected: ETH sale consumes ETH lot, cost=3000, P&L=+500
# Actual: ETH sale consumes BTC lot, cost=50000, P&L=-46500
```

**Actual behavior observed**:
- ETH disposal linked to BTC lot (`lot_id` of the BTC acquisition)
- BTC lot `remaining_quantity` went to 0 (incorrectly depleted)
- ETH lot `remaining_quantity` stayed at 1 (never consumed)
- `cost_allocated` = 50,000 (BTC cost) instead of 3,000 (ETH cost)
- `realized_pnl` = -46,500 instead of +500

**Root cause**: In `engine.py`, `_process_disposal` calls:
```python
plan = self._method.select_lots(
    available_lots=all_lots,  # ALL lots, all assets
    ...
)
```

And `FIFOMethod.select_lots` does not filter `available_lots` by `lot.asset == asset`.

The same bug exists in `_process_swap_pair` (swaps.py) where `available_lots=lots` is passed without asset filtering.

**Financial impact**: HIGH. Any user holding more than one asset will see completely incorrect P&L when disposing of any asset. The error magnitude equals the price difference between the disposed asset and the incorrectly consumed lot.

**Recommended fix**: In `FIFOMethod.select_lots`, filter `available_lots` to only include lots where `lot.asset == asset` before sorting and iterating. Apply the same fix in `swaps.py` if needed.

---

## 5. P1 Findings

No new P1 findings discovered during M023.

---

## 6. P2 Findings

No new P2 findings discovered during M023.

---

## 7. P3 Findings

No new P3 findings discovered during M023.

---

## 8. M022 Remediation Verification

### P0-1 — Fee acquisition fabrication
**Status**: PASS
- `apply_acquisition_fee` no longer fabricates cost basis when `cost_basis` is `None`
- Test: `test_quote_asset_fee_with_missing_cost_basis_does_not_fabricate` passes

### P0-2 — Fee disposal fabrication
**Status**: PASS
- `apply_disposal_fee` no longer creates negative proceeds when `proceeds` is `None`
- Test: `test_quote_asset_fee_with_missing_proceeds_does_not_fabricate_negative` passes

### P0-3 — Swap valuation fallback
**Status**: PASS
- `_process_swap_pair` falls back to `disposal_proceeds` when output leg lacks valuation
- Tests: `test_swap_acquisition_uses_disposal_proceeds_when_output_leg_missing_value` passes

### P0-4 — Currency mismatch validation
**Status**: PASS
- Currency mismatch produces `CURRENCY_MISMATCH` warning and `realized_pnl = None`
- Test: `test_currency_mismatch_produces_warning_and_null_pnl` passes

### P1-1 — Duplicate transaction filtering
**Status**: PASS
- `unique_transaction_ids` correctly filters duplicates
- Engine tracks `processed_tx_ids` to prevent double-counting
- Tests: `test_duplicate_buy_does_not_double_count_lots`, `test_duplicate_sell_does_not_double_count_pnl` pass

### P1-2/P1-5 — P&L currency aggregation
**Status**: PASS
- `_aggregate_realized_pnl` groups by currency
- Test: `test_realized_pnl_aggregated_by_currency` passes

### P1-3 — Transfer lot preservation
**Status**: PASS
- `process_transfer` links source lots via `linked_lot_ids`
- Test: `test_matched_transfer_links_lots` passes

### P1-4 — Cross-exchange transfer matching
**Status**: PASS
- `TransferReconciler` matches cross-exchange transfers when `tx_hash` matches
- Test: `test_cross_exchange_transfer_matched_with_tx_hash` passes

---

## 9. Accounting Mathematical Verification

### FIFO Scenarios

| Scenario | Expected | Actual | Status |
|---|---|---|---|
| BUY 1 @ 30k, SELL 1 @ 35k | P&L = +5,000 | +5,000 | PASS |
| BUY 1 @ 30k, BUY 1 @ 32k, SELL 1 @ 35k | FIFO cost = 30,000, P&L = +5,000 | 30,000 / +5,000 | PASS |
| BUY 1 @ 30k, BUY 1 @ 32k, SELL 1.5 @ 35k | Cost = 46,000, remaining = 0.5+0.5 | 46,000 / 0.5+0.5 | PASS |
| Same timestamp, different costs | Deterministic by lot_id | Deterministic | PASS |
| **Cross-asset: ETH bought, BTC bought, sell ETH** | **ETH cost = 3,000, P&L = +500** | **BTC cost = 50,000, P&L = -46,500** | **FAIL** |

### Fee Scenarios

| Scenario | Expected | Actual | Status |
|---|---|---|---|
| Quote-asset fee on BUY (known cost) | Cost += fee | Correct | PASS |
| Quote-asset fee on BUY (missing cost) | No fabrication | None + warning | PASS |
| Quote-asset fee on SELL (known proceeds) | Proceeds -= fee | Correct | PASS |
| Quote-asset fee on SELL (missing proceeds) | No fabrication | None + warning | PASS |
| Base-asset fee on BUY | Quantity -= fee | Correct | PASS |
| Base-asset fee on SELL | Quantity -= fee | Correct | PASS |

### Swap Scenarios

| Scenario | Expected | Actual | Status |
|---|---|---|---|
| Both legs valued | Correct disposal/acquisition | Correct | PASS |
| Output missing, disposal available | Fallback to disposal proceeds | Correct | PASS |
| Both missing | No fabrication | None + warning | PASS |

---

## 10. Determinism Verification

**Status**: PASS

- All IDs use SHA-256 of sorted deterministic inputs
- FIFO sorts by `(acquired_timestamp, lot_id)`
- Swap groups sort by timestamp then asset
- P&L aggregation sorts by `(currency, from_timestamp)`
- Duplicate filtering uses `set` membership
- No UUIDs, no `datetime.now()`, no randomness
- `test_deterministic_result` and `test_fifo_identical_timestamps_deterministic` pass

**Caveat**: The cross-asset bug (P0-1) does not affect determinism — the wrong lot is chosen deterministically. Determinism and correctness are independent properties.

---

## 11. Immutability Verification

**Status**: PASS

- `CanonicalTransaction` has `ConfigDict(frozen=True)`
- `AccountingEvent`, `AcquisitionLot`, `LotConsumption`, `RealizedPnL` all frozen
- Engine never mutates input transactions
- `test_canonical_transaction_not_mutated` passes
- `test_canonical_transaction_not_mutated_by_swap` passes

---

## 12. API/Pipeline Verification

**Status**: PASS

- `/api/v1/account` runs full pipeline with accounting
- `/api/v1/process?accounting=true` includes accounting in ProcessingResult
- 400 for missing timezone, 207 for partial errors, 500 for exceptions
- Decimal serialization via Pydantic `model_dump(mode="json")` preserves precision
- No stack traces, no local paths, no secrets in API responses
- `test_api_account_endpoint` passes
- `test_api_process_with_accounting_flag` passes

---

## 13. Performance Findings

**Status**: PASS (within observed bounds)

- 100 transactions processed in < 5 seconds
- FIFO O(n log n) per disposal — acceptable for typical user datasets
- Duplicate detection bounded by `max_fingerprint_bucket_size`
- No memory leaks observed in test scenarios

No performance bottlenecks require attention for production use with Binance/Coinbase exports.

---

## 14. M020 Specification Compliance Matrix

| Spec Requirement | Implementation | Status |
|---|---|---|
| FIFO lot ordering by timestamp + lot_id | Correct (within single asset) | PARTIAL — P0 cross-asset bug |
| Partial lot consumption | Supported | PASS |
| Insufficient lots warning/error | Implemented | PASS |
| Quote-asset fee on BUY adds to cost | Correct when cost known; no fabrication when missing | PASS |
| Quote-asset fee on SELL reduces proceeds | Correct when proceeds known; no fabrication when missing | PASS |
| Base-asset fee on BUY reduces quantity | Correct | PASS |
| Base-asset fee on SELL reduces quantity | Correct | PASS |
| Third-asset fee warning | Correct | PASS |
| Missing fee asset warning | Correct | PASS |
| Transfer matched → no lots created | Correct; preserves lot linkage | PASS |
| Transfer unmatched → warning | Correct | PASS |
| Swap disposal consumes FIFO lots | Correct (within single asset); **cross-asset bug** | PARTIAL |
| Swap acquisition creates lot | Correct | PASS |
| Swap valuation fallback | Implemented | PASS |
| Currency mismatch → null P&L | Correct | PASS |
| Duplicate deduplication | Implemented | PASS |
| Withdrawal as NON_ACCOUNTING | Per M020-A behavior | PASS (spec drift noted in M021) |
| Deterministic IDs | All SHA-256 based | PASS |
| Decimal integrity | All financial fields Decimal | PASS |
| Immutability | Frozen models, no mutation | PASS |
| API `/api/v1/account` | Implemented | PASS |
| API `/api/v1/process?accounting=true` | Implemented | PASS |

---

## 15. Regression Assessment

M022 remediation did not introduce any regressions in the areas it fixed. All 12 new M022 regression tests pass. The M022 fixes for fees, swaps, currency validation, duplicates, P&L aggregation, transfers, and cross-exchange matching are all verified as correct.

The cross-asset FIFO bug (P0-1) is a **pre-existing** issue that was not identified in M021 or M022 because:
1. M021 focused on fee fabrication, swap valuation, currency mismatch, and duplicates
2. M022 tests primarily used single-asset scenarios
3. The bug only manifests when multiple assets coexist in the lot pool

This is not a regression from M022 — it is a newly discovered pre-existing defect.

---

## 16. Remaining Risks

### P0 — Cross-asset lot consumption (NEW)
The FIFO engine consumes lots without verifying asset compatibility. This affects:
- Regular disposals (SELL)
- Swap disposals
- Any scenario with multiple assets in the lot pool

**Risk**: Materially incorrect P&L, cost basis, and inventory for any multi-asset portfolio.

### P2 — Withdrawal classification
Still treated as `NON_ACCOUNTING` per M020-A. The M020 spec §3.4 describes it as `DISPOSAL` with `proceeds=0`. This is a known spec drift that was not addressed in M022.

### P3 — Cross-exchange transfer matching
Requires matching `tx_hash`. If exchanges do not provide transaction hashes in exports, cross-exchange transfers remain unmatched. This is a safe limitation but should be documented.

---

## 17. Recommended Next Milestone

**M024 — P0 Cross-Asset Bug Fix & Final Validation**

Required actions:
1. **Fix P0-1**: Add asset filtering to `FIFOMethod.select_lots` and verify swap handler also filters correctly
2. **Add regression tests**: Multi-asset FIFO scenarios, cross-asset swap disposals
3. **Re-run full audit**: Verify no new defects introduced by the fix
4. **Final acceptance**: M023 can be marked ACCEPTED only after P0-1 is remediated

Do NOT add new exchanges. Do NOT expand scope beyond P0 fix and validation.

---

## 18. Final Verdict

**M023 NOT ACCEPTED**

The adversarial audit discovered a P0 cross-asset lot consumption bug that makes the accounting engine financially incorrect for any multi-asset portfolio. While all M022 remediations verified as correct, this new critical defect prevents acceptance.

**Next step**: M024 to fix the asset-filtering bug in FIFO lot selection and swap disposal handling.
