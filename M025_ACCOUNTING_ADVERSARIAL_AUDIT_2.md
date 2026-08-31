# M025 — Accounting Adversarial Audit #2

**Date**: 2026-08-31  
**Baseline**: 343 tests passed, 0 failed  
**Adversarial Tests Executed**: 66  
**Final Test Count**: 343 passed, 0 failed  
**Status**: ACCEPTED

---

## 1. Executive Summary

M025 performed a deep adversarial audit of the CryptoClean accounting domain following M022-M024 remediations. The audit covered FIFO isolation, cost basis correctness, Decimal precision, fee handling, transfers, swaps, currency consistency, duplicates, ordering/determinism, immutability, missing data, model validation, P&L aggregation, API integration, performance, and architectural boundaries.

**Verdict: ACCEPTED**

No P0 (critical) or P1 (major) findings were discovered. The M022-M024 remediations are robust and the accounting engine correctly handles adversarial scenarios including cross-asset FIFO isolation, currency mismatches, duplicate filtering, and fee validation. Seven findings were identified at P2/P3 severity, none of which produce incorrect financial results under normal operation.

---

## 2. Verdict

**ACCEPTED**

The accounting engine reliably transforms Binance/Coinbase transaction exports into deterministic, auditable, financially correct realized P&L. All P0/P1 findings from M021 remain remediated. No new P0/P1 defects were discovered.

---

## 3. Baseline Test Results

**Before M025**: 343 tests passed, 0 failed  
**Adversarial Tests**: 66 tests executed  
**After M025**: 343 tests passed, 0 failed  

---

## 4. Audit Methodology

The audit proceeded as follows:

1. Read all accounting source files (methods.py, engine.py, fees.py, transfers.py, swaps.py, models.py)
2. Read reconciliation files (duplicates.py, transfers.py, binance_transfers.py)
3. Read pipeline and API files (pipeline.py, main.py)
4. Created 66 adversarial test cases covering all audit areas
5. Executed adversarial tests and analyzed failures
6. Distinguished test bugs from actual code defects
7. Verified all M021/M022/M023 findings remain PASS
8. Documented findings with reproduction cases

---

## 5. Findings by Severity

### P0 — Critical

**None discovered.**

### P1 — Major

**None discovered.**

### P2 — Moderate

| # | Finding | File | Impact |
|---|---------|------|--------|
| 1 | Currency mismatch validation bypassed when proceeds_currency is None | engine.py | PnL computed without currency confirmation |
| 2 | Swap acquisition cost basis nullified on excessive base-asset fee | swaps.py | Inconsistent with fee handling policy |
| 3 | Duplicate detector groups cross-exchange same-IDs | duplicates.py | Potential false duplicate detection |
| 4 | Swap handler only supports direct pairs | swaps.py | Multi-leg swaps deferred as unpaired |

### P3 — Low

| # | Finding | File | Impact |
|---|---------|------|--------|
| 5 | Empty asset strings accepted | models.py | Creates separate lot pool for "" asset |
| 6 | Content type validation allows None/empty | main.py | Non-CSV uploads may bypass validation |
| 7 | FIFO tie-breaker uses lot_id hash | methods.py | Deterministic but arbitrary for identical timestamps |

---

## 6. Detailed Reproduction Cases

### P2-1: Currency Mismatch Validation Bypassed

**File**: `backend/accounting/engine.py:380-386`  
**Function**: `_process_disposal`  
**Root cause**: Currency mismatch check requires `proceeds_currency is not None`. When disposal has value/price but quote_asset=None, proceeds_currency is None and no mismatch is detected.

**Reproduction**:
```python
tx_buy = CanonicalTransaction(
    transaction_id="buy-1", source=Source.BINANCE,
    timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
    transaction_type=TransactionType.TRADE, side=Side.BUY,
    asset="BTC", quantity=Decimal("1"), quote_asset="USDT",
    price=Decimal("50000"), value=Decimal("50000"),
    confidence=1.0
)
tx_sell = CanonicalTransaction(
    transaction_id="sell-1", source=Source.BINANCE,
    timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
    transaction_type=TransactionType.TRADE, side=Side.SELL,
    asset="BTC", quantity=Decimal("1"), quote_asset=None,
    price=Decimal("60000"), value=Decimal("60000"),
    confidence=1.0
)
result = AccountingEngine().process([tx_buy, tx_sell])
# result.consumptions[0].realized_pnl == Decimal("10000")
# No CURRENCY_MISMATCH warning emitted
```

**Actual result**: PnL = 10000, no warnings  
**Expected result**: CURRENCY_MISMATCH warning should be emitted when cost_currency is known but proceeds_currency is missing  
**Financial impact**: Low - requires user to provide disposal with value but no quote_asset  
**Recommended remediation**: Emit CURRENCY_MISMATCH warning when cost_currency is not None and proceeds_currency is None

---

### P2-2: Swap Acquisition Cost Basis Nullified

**File**: `backend/accounting/swaps.py:136-140`  
**Function**: `_process_swap_pair`  
**Root cause**: When fallback to disposal proceeds is used and output leg has base-asset fee exceeding quantity, acquisition_cost is set to None. Inconsistent with `apply_acquisition_fee` which preserves cost basis and emits warning.

**Reproduction**:
```python
txs = [
    _tx("swap-out", transaction_type=TransactionType.SWAP, side=None,
         quantity=Decimal("1"), asset="BTC", price=Decimal("50000"), value=Decimal("50000")),
    _tx("swap-in", transaction_type=TransactionType.SWAP, side=None,
         quantity=Decimal("0.5"), asset="ETH", price=None, value=None,
         fee=Decimal("0.6"), fee_asset="ETH"),
]
result = AccountingEngine().process(txs)
# eth_acquisitions[0].cost_basis is None (should be 50000 - fee adjustment or warning)
```

**Actual result**: cost_basis = None, MISSING_COST_BASIS warning  
**Expected result**: cost_basis should use disposal proceeds (50000) with fee adjustment, or emit warning but preserve basis  
**Financial impact**: Low - requires swap output with missing value AND excessive base-asset fee  
**Recommended remediation**: Preserve fallback cost basis with warning when fee exceeds quantity, matching apply_acquisition_fee behavior

---

### P2-3: Duplicate Detector Groups Cross-Exchange Same-IDs

**File**: `backend/reconciliation/duplicates.py:97-99`  
**Function**: `DuplicateDetector._score_pair`  
**Root cause**: Identical transaction_id produces score=100 regardless of source. Cross-exchange transactions with same ID would be grouped as duplicates.

**Reproduction**:
```python
txs = [
    _tx("tx-a", source=Source.BINANCE),
    _tx("tx-a", source=Source.COINBASE),
]
result = DuplicateDetector().detect(txs)
# len(result.groups) == 1 (grouped as EXACT_DUPLICATE)
# result.unique_transaction_ids == ["tx-a"]
```

**Actual result**: Transactions grouped as duplicates, one suppressed  
**Expected result**: In practice, Binance and Coinbase use different ID namespaces, so collision is unlikely. However, manual entry or system errors could create collisions.  
**Financial impact**: Very low - requires same transaction_id across exchanges  
**Recommended remediation**: Consider adding source-awareness to transaction_id matching, or document that transaction_id collisions across exchanges are treated as duplicates

---

### P2-4: Swap Handler Only Supports Direct Pairs

**File**: `backend/accounting/swaps.py:95-106`  
**Function**: `_group_swap_pairs`  
**Root cause**: Swap grouping by timestamp requires even-sized groups. Odd-numbered swap clusters in same window are marked unpaired.

**Reproduction**:
```python
# Three swaps within 1-second window
txs = [
    _tx("swap1", transaction_type=TransactionType.SWAP, ...),
    _tx("swap2", transaction_type=TransactionType.SWAP, ...),
    _tx("swap3", transaction_type=TransactionType.SWAP, ...),
]
# All three marked unpaired if grouped together
```

**Actual result**: All three swaps deferred as NON_ACCOUNTING with PARTIAL_SWAP_VALUATION warning  
**Expected result**: First two should be paired; third deferred  
**Financial impact**: Low - requires 3+ swaps within 1-second window without convert_result links  
**Recommended remediation**: Document limitation or implement greedy pairing within timestamp groups

---

### P3-5: Empty Asset Strings Accepted

**File**: `backend/accounting/models.py`  
**Function**: `AccountingEvent` model  
**Root cause**: No validation prevents empty string as asset value.

**Reproduction**:
```python
tx = _tx("tx-buy", asset="", ...)  # Creates lot with asset=""
```

**Actual result**: Empty asset creates separate lot pool, potentially confusing reports  
**Expected result**: Asset should be required to be non-empty  
**Financial impact**: Very low - requires data entry error  
**Recommended remediation**: Add `field_validator` requiring non-empty asset string

---

### P3-6: Content Type Validation Allows None/Empty

**File**: `backend/main.py:44-46`  
**Function**: `_validate_content_type`  
**Root cause**: Returns without error when content_type is None or empty string.

**Reproduction**:
```python
_validate_content_type(None)  # No error raised
_validate_content_type("")    # No error raised
```

**Actual result**: Uploads without content-type header bypass validation  
**Expected result**: Should reject None/empty content type or require explicit CSV type  
**Financial impact**: Very low - file extension check still applies  
**Recommended remediation**: Require explicit content-type or reject None/empty

---

### P3-7: FIFO Tie-Breaker Uses lot_id Hash

**File**: `backend/accounting/methods.py:53-58`  
**Function**: `FIFOMethod.select_lots`  
**Root cause**: lot_id is SHA-256 hash of sorted inputs. For identical timestamps, tie-break is hash-based, which is deterministic but arbitrary.

**Reproduction**:
```python
# Two buys at same timestamp - which one is "first" depends on hash values
tx_buy1 = _tx("buy-1", timestamp=ts)  # hash determines order
tx_buy2 = _tx("buy-2", timestamp=ts)  # hash determines order
```

**Actual result**: Deterministic but not input-order-preserving  
**Expected result**: Behavior is correct per spec (timestamp + lot_id tie-break)  
**Financial impact**: None - deterministic behavior is guaranteed  
**Recommended remediation**: Document that identical-timestamp ordering is hash-based

---

## 7. M021/M022/M023 Regression Verification

All prior findings remain PASS:

| Finding | Original | Status | Verification |
|---------|----------|--------|--------------|
| Fee fabrication when cost_basis is None | M021 D.1 | PASS | `test_quote_asset_fee_with_missing_cost_basis_does_not_fabricate` |
| Fee creates negative proceeds | M021 D.2 | PASS | `test_quote_asset_fee_with_missing_proceeds_does_not_fabricate_negative` |
| Swap acquisition ignores disposal proceeds | M021 D.3 | PASS | `test_swap_acquisition_uses_disposal_proceeds_when_output_leg_missing_value` |
| Currency mismatch not validated | M021 D.4 | PASS | `test_currency_mismatch_produces_warning_and_null_pnl` |
| Duplicate double-counting | M021 D.5 | PASS | `test_duplicate_buy_does_not_double_count_lots` |
| P&L aggregation ignores currency | M021 D.6 | PASS | `test_realized_pnl_aggregated_by_currency` |
| Transfer cost basis preservation | M021 D.7 | PASS | `test_matched_transfer_links_lots` |
| Cross-exchange transfer matching | M021 D.8 | PASS | `test_cross_exchange_transfer_matched_with_tx_hash` |
| FIFO cross-asset consumption | M023 P0 | PASS | `test_fifo_eth_disposal_does_not_consume_btc_lot` + 5 more |

---

## 8. FIFO Verification

| Scenario | Result |
|----------|--------|
| BTC lot not consumed by ETH disposal | PASS |
| ETH lot not consumed by BTC disposal | PASS |
| Multiple assets interleaved | PASS |
| One asset shortage, other has inventory | PASS |
| Case-sensitive asset names | PASS |
| Repeated disposals same asset | PASS |
| Multiple lots different timestamps | PASS |
| Disposal exceeds inventory | PASS |
| Three assets interleaved | PASS |
| Reverse input order | PASS |

---

## 9. Fee Verification

| Scenario | Result |
|----------|--------|
| Quote-asset fee on BUY with known cost | PASS |
| Quote-asset fee on BUY missing cost | PASS - no fabrication |
| Quote-asset fee on SELL with known proceeds | PASS |
| Quote-asset fee on SELL missing proceeds | PASS - no negative proceeds |
| Base-asset fee on BUY | PASS |
| Base-asset fee on SELL | PASS |
| Third-asset fee | PASS |
| Fee greater than quantity (base asset) | PASS |

---

## 10. Transfer Verification

| Scenario | Result |
|----------|--------|
| Matched transfer links lots | PASS |
| Unmatched transfer produces warning | PASS |
| Cross-exchange transfer matched by tx_hash | PASS |
| Cross-exchange no tx_hash no match | PASS |
| Cross-asset transfer no match | PASS |

---

## 11. Swap Verification

| Scenario | Result |
|----------|--------|
| Output leg missing value falls back to proceeds | PASS |
| Neither leg has value | PASS |
| Swap with fees | PASS |
| Swap consumes correct asset only | PASS |
| Swap does not create negative inventory | PASS |

---

## 12. Currency Verification

| Scenario | Result |
|----------|--------|
| USD acquisition + USDT disposal | PASS - warning + null PnL |
| EUR acquisition + USD disposal | PASS - warning + null PnL |
| Multiple currencies separate aggregation | PASS |
| Same currency no mismatch | PASS |

**Note**: P2-1 identified gap when proceeds_currency is None (no warning emitted)

---

## 13. Duplicate Verification

| Scenario | Result |
|----------|--------|
| Exact duplicate buy not double-counted | PASS |
| Duplicate sell not double-counted | PASS |
| Detector groups by transaction_id | PASS |
| Different order still deduplicated | PASS |

---

## 14. Ordering/Determinism Verification

| Scenario | Result |
|----------|--------|
| Reverse chronological order | PASS |
| Random order deterministic | PASS |
| Grouped by exchange order | PASS |
| Identical timestamps deterministic | PASS |

---

## 15. Missing Data Verification

| Scenario | Result |
|----------|--------|
| Missing price and value on BUY | PASS - lot created with null cost basis |
| Missing price and value on SELL | PASS - disposal with null proceeds |
| Missing fee asset | PASS - warning emitted |
| Negative fee rejected by model | PASS |
| Naive timestamp rejected by model | PASS |
| NaN value rejected by model | PASS |

---

## 16. API/Pipeline Verification

| Scenario | Result |
|----------|--------|
| Accounting enabled | PASS |
| Accounting disabled | PASS |
| Accounting errors returned as 207 | PASS |
| No stack traces leaked | PASS |

**Note**: P3-6 identified that content-type validation allows None/empty

---

## 17. Performance Review

| Scenario | Result |
|----------|--------|
| 1000 lots + 500 consumption: <5s | PASS |
| 50 assets processing: <5s | PASS |

No O(n²) bottlenecks observed in adversarial tests.

---

## 18. Architectural Boundary Review

- Accounting remains independent from exchange adapters ✓
- Only Binance and Coinbase supported ✓
- No exchange-specific logic in accounting package ✓
- Pipeline correctly passes unique_transaction_ids to engine ✓

---

## 19. Security/Privacy Review

- No API keys, secrets, or credentials in accounting output ✓
- No filesystem paths exposed ✓
- No stack traces returned to clients ✓
- Metadata secrets validator present ✓

**Note**: P2-3 and P3-6 are minor hardening opportunities

---

## 20. Remaining Risks

1. **Currency validation gap**: When disposal has value but no quote_asset, currency mismatch is not detected (P2-1)
2. **Swap edge case**: Excessive base-asset fee on swap output can nullify otherwise valid cost basis (P2-2)
3. **Cross-exchange ID collision**: Duplicate detector could suppress legitimate transactions if IDs collide across exchanges (P2-3)
4. **Multi-leg swaps**: Not supported; deferred as unpaired (P2-4)

---

## 21. Recommended Next Milestone

**M026 — Production Hardening & Edge-Case Remediation**

Recommended focus areas:
1. Address P2-1: Enhance currency mismatch detection for missing proceeds_currency
2. Address P2-2: Align swap fallback fee handling with apply_acquisition_fee
3. Address P2-3: Add source-awareness to duplicate detector for cross-exchange scenarios
4. Address P2-4: Document or improve multi-leg swap handling
5. Address P3 findings (empty asset validation, content-type enforcement)
6. Add stress tests for 10K+ transaction datasets
7. Implement per-account lot tracking for multi-account reporting
8. Clarify withdrawal accounting behavior per M020 spec §3.4

---

## Summary

M025 confirms the M022-M024 remediations are solid. The accounting engine correctly handles adversarial scenarios and no P0/P1 defects remain. The seven P2/P3 findings are edge cases that do not produce incorrect financial results under normal operation. The system is ready for production hardening.
