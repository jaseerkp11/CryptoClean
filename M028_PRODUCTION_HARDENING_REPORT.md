# M028 Production Deployment Hardening Report

> **Status**: COMPLETE
> **Generated**: 2026-08-31
> **Baseline**: 361 tests passed, 0 failed (M027)
> **Final**: 379 tests passed, 0 failed
> **Test delta**: +18 tests (17 M028 hardening tests + 1 new withdrawal test)

---

## 1. Executive Summary

M028 addresses the M027 P2 and P3 findings while preserving all prior accounting correctness fixes. The milestone focuses on production hardening: content-type validation, empty asset validation, withdrawal accounting spec alignment, path traversal protection, security headers, and API production readiness.

### Key Changes

| Category | Change | Status |
|---|---|---|
| Content-type validation | Now rejects missing/empty content-type | COMPLETE |
| Empty asset validation | CanonicalTransaction rejects blank assets | COMPLETE |
| Withdrawal accounting | Aligned with M020 spec (DISPOSAL events) | COMPLETE |
| Path traversal protection | All endpoints reject path separators | COMPLETE |
| Security headers | X-Content-Type-Options, X-Frame-Options, etc. | COMPLETE |
| Multi-hop swap docs | Documented limitation in architecture spec | COMPLETE |
| FIFO tie-breaking | Reviewed and confirmed deterministic | COMPLETE |
| Unused code cleanup | Removed unused SENSITIVE_KEYWORDS | COMPLETE |

---

## 2. M027 Findings Remediation

### 2.1 P2 Findings

| # | Finding | Status | Fix |
|---|---|---|---|
| 1 | Content type validation allows None/empty | FIXED | `_validate_content_type` now rejects missing/empty content-type with HTTP 400 |
| 2 | Empty asset strings accepted by canonical model | FIXED | Added `asset_not_blank` field validator to `CanonicalTransaction` |
| 3 | FIFO tie-breaker uses lot_id hash | ACCEPTED | Deterministic behavior documented; no code change needed |

### 2.2 P3 Findings

| # | Finding | Status | Fix |
|---|---|---|---|
| 4 | Multi-hop swap limitation not documented | FIXED | Added §11.4.1 to ARCHITECTURE_SPEC.md |
| 5 | Withdrawal accounting differs from M020 spec §3.4 | FIXED | Withdrawals now create DISPOSAL events with proceeds (0 or market value) |
| 6 | No per-account lot tracking | DEFERRED | Documented as future work; current implementation uses asset-level lots |
| 7 | Temporary CSV files in system temp | ACCEPTED | Files are cleaned up in finally block; no sensitive data leakage |

---

## 3. Implementation Details

### 3.1 Content-Type Hardening (`backend/main.py`)

**Before:**
```python
def _validate_content_type(content_type: Optional[str]) -> None:
    if not content_type:
        return  # Silently allowed missing content-type
    ...
```

**After:**
```python
def _validate_content_type(content_type: Optional[str]) -> None:
    if not content_type:
        raise HTTPException(
            status_code=400,
            detail="Content-Type header is required.",
        )
    ...
```

**Impact**: All three API endpoints (`/api/v1/ingest`, `/api/v1/process`, `/api/v1/account`) now require a valid Content-Type header.

### 3.2 Empty Asset Validation (`backend/models/transaction.py`)

Added field validator:
```python
@field_validator("asset")
@classmethod
def asset_not_blank(cls, v: str) -> str:
    if not v or not v.strip():
        raise ValueError("asset cannot be blank.")
    return v.strip()
```

**Impact**: Empty or whitespace-only asset strings are rejected at the model level.

### 3.3 Withdrawal Accounting Alignment (`backend/accounting/engine.py`)

**Before:** Withdrawals created `NON_ACCOUNTING` events with no cost basis computation.

**After:** Withdrawals create `DISPOSAL` events:
- Proceeds = 0 if no value/price available
- Proceeds = market value if `value` or `price * quantity` available
- Cost basis consumed per cost-basis method
- `WITHDRAWAL_NO_PROCEEDS` warning only when proceeds = 0

This aligns with M020 spec §3.4:
> - Creates an `AccountingEvent` of type `DISPOSAL`.
> - Withdrawal is treated as a disposal at `proceeds = 0` (or `None` if unknown).
> - If `value` or `price` is available and represents market value at withdrawal, that may be used as proceeds; otherwise proceeds = 0.
> - Produces `WITHDRAWAL_NO_PROCEEDS` warning when proceeds = 0.

### 3.4 Path Traversal Protection (`backend/main.py`)

Added to all three upload endpoints:
```python
if os.path.sep in file.filename or (os.path.altsep and os.path.altsep in file.filename):
    raise HTTPException(status_code=400, detail="Invalid filename.")
```

### 3.5 Security Headers Middleware (`backend/main.py`)

Added HTTP middleware:
```python
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Cache-Control"] = "no-store"
    return response
```

### 3.6 Health Endpoint Enhancement (`backend/main.py`)

Added version field to health response:
```python
class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
```

### 3.7 Unused Code Cleanup (`backend/ingestion/reader.py`)

Removed unused `SENSITIVE_KEYWORDS` list (sensitive key detection is handled in `transaction.py` model validator).

### 3.8 Multi-Hop Swap Documentation (`ARCHITECTURE_SPEC.md`)

Added §11.4.1:
> The swap handler pairs transactions within a single timestamp window using greedy pairing. Multi-hop swaps (e.g., BTC → ETH → USDT) that span multiple timestamp windows are **not automatically linked**:
> - Each hop is treated as an independent swap event
> - Cost basis is computed per-hop using the disposal proceeds of the previous hop
> - Users should ensure all hops of a multi-hop swap share the same timestamp window for correct pairing
> - This is a known limitation; future work may add cross-window swap chain detection

---

## 4. Test Coverage

### 4.1 New Tests (`backend/tests/test_m028_production_hardening.py`)

| Test Class | Tests | Coverage |
|---|---|---|
| TestContentTypeHardening | 4 | Missing, empty, invalid, valid content-type |
| TestPathTraversalProtection | 2 | Forward slash, backslash in filename |
| TestSecurityHeaders | 1 | X-Content-Type-Options, X-Frame-Options, etc. |
| TestEmptyAssetValidation | 3 | Empty, whitespace, valid asset |
| TestWithdrawalAccountingAlignment | 3 | Disposal event creation, no proceeds warning, value as proceeds |
| TestProcessEndpointHardening | 2 | Content-type, path traversal |
| TestAccountEndpointHardening | 2 | Content-type, path traversal |

### 4.2 Updated Tests (`backend/tests/test_accounting.py`)

| Test | Change |
|---|---|
| `test_withdrawal_is_non_accounting` → `test_withdrawal_is_disposal` | Updated to reflect DISPOSAL event type |
| `test_withdrawal_no_value_produces_warning` | New test for WITHDRAWAL_NO_PROCEEDS warning |

### 4.3 Test Results

```
379 passed, 1 warning in 56.67s
```

Breakdown:
- Original baseline: 361 tests
- M028 hardening tests: 17 tests
- Updated withdrawal test: 1 test (split into 2)
- **Total new tests: +18**

---

## 5. Files Modified

| File | Changes |
|---|---|
| `backend/main.py` | Content-type hardening, path traversal, security headers, health endpoint |
| `backend/models/transaction.py` | Empty asset validator |
| `backend/accounting/engine.py` | Withdrawal accounting alignment |
| `backend/ingestion/reader.py` | Removed unused SENSITIVE_KEYWORDS |
| `ARCHITECTURE_SPEC.md` | Multi-hop swap documentation |
| `backend/tests/test_m028_production_hardening.py` | New test file (17 tests) |
| `backend/tests/test_accounting.py` | Updated withdrawal tests |

---

## 6. Deployment Considerations

### 6.1 Authentication

Authentication is NOT implemented in this milestone. It is deployment infrastructure that should be handled by:
- Reverse proxy (nginx, traefik) with OAuth/OIDC
- API gateway with JWT validation
- Cloud provider IAM (AWS API Gateway, Azure API Management)

### 6.2 Infrastructure

Docker/Kubernetes deployment configs are NOT included. They should be created as separate deployment artifacts.

### 6.3 Environment Configuration

The application should be configured via environment variables for:
- Database connection (when added)
- Logging level
- CORS origins (when frontend is deployed)
- Rate limiting thresholds

### 6.4 Monitoring

The `/health` endpoint now includes version information for deployment verification.

---

## 7. Remaining Risks

| Risk | Severity | Mitigation |
|---|---|---|
| No authentication | P2 | Deploy behind reverse proxy with OAuth |
| No rate limiting | P3 | Add middleware or use API gateway |
| No CORS configuration | P3 | Add CORS middleware for production |
| No database persistence | P3 | All processing is in-memory |
| Multi-hop swap limitation | P3 | Documented; future work |
| Per-account lot tracking | P3 | Future enhancement |

---

## 8. Next Milestone

M029 should focus on:
1. Final adversarial verification of all M028 changes
2. Performance testing with large CSV files
3. User acceptance testing
4. Production deployment runbook

---

## 9. Verification

All M028 changes have been verified against the M027 findings:

- [x] P2-1: Content-type validation hardened
- [x] P2-2: Empty asset validation added
- [x] P2-3: FIFO tie-breaking confirmed deterministic
- [x] P3-4: Multi-hop swap limitation documented
- [x] P3-5: Withdrawal accounting aligned with M020 spec
- [x] P3-6: Per-account lot tracking deferred (documented)
- [x] P3-7: Temporary file handling reviewed (cleanup in place)

**M028 Status: COMPLETE**
