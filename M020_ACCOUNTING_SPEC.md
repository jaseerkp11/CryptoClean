# M020 — Accounting Engine Design Specification

> **Status**: Design phase. No implementation yet.
> **Baseline**: M019 accepted; 264 tests passing, 0 failing.
> **Scope**: Deterministic crypto accounting foundation (cost basis, lot tracking, realized P&L).

---

## 1. Executive Summary

M020 introduces a separate accounting domain layer that consumes immutable canonical transactions and reconciliation results to produce auditable cost-basis tracking, lot consumption, and realized P&L. The accounting engine is configurable, deterministic, and never mutates source data. It deliberately does not implement unrealized P&L, tax jurisdiction rules, or live market pricing.

---

## 2. Domain Model

### 2.1 AccountingEvent

**Purpose**: Represents a single accounting-relevant action derived from one or more canonical transactions.

**Fields**:
| Field | Type | Notes |
|---|---|---|
| `event_id` | `str` | Deterministic identity |
| `event_type` | `AccountingEventType` | ACQUISITION, DISPOSAL, TRANSFER, SWAP, FEE, WARNING |
| `source_transaction_ids` | `List[str]` | Canonical transaction IDs that caused this event |
| `timestamp` | `datetime` | Timezone-aware; from source transaction |
| `asset` | `str` | Asset affected |
| `quantity` | `Decimal` | Positive for acquisitions; positive for disposals (absolute) |
| `cost_basis` | `Optional[Decimal]` | Total cost in cost currency |
| `cost_currency` | `Optional[str]` | Currency in which cost is denominated |
| `proceeds` | `Optional[Decimal]` | Total proceeds in proceeds currency |
| `proceeds_currency` | `Optional[str]` | Currency in which proceeds are denominated |
| `realized_pnl` | `Optional[Decimal]` | Proceeds minus cost basis (same currency) |
| `pnl_currency` | `Optional[str]` | Currency of realized P&L |
| `fee` | `Optional[Decimal]` | Fee amount |
| `fee_asset` | `Optional[str]` | Asset in which fee was paid |
| `linked_lot_ids` | `List[str]` | Acquisition lots consumed by this event |
| `warnings` | `List[str]` | Non-fatal accounting warnings |
| `metadata` | `Optional[Dict[str, Any]]` | Source-specific context |

**Identity**: SHA-256 of `event_type`, sorted `source_transaction_ids`, `asset`, `quantity`, `timestamp`.

**Immutability**: Frozen. Events are append-only.

**Relationships**: One event may reference multiple acquisition lots (partial consumption across lots). One acquisition lot may be referenced by multiple disposal events (partial consumption).

---

### 2.2 AcquisitionLot

**Purpose**: Represents a block of asset acquired at a known cost, available for future consumption by disposals.

**Fields**:
| Field | Type | Notes |
|---|---|---|
| `lot_id` | `str` | Deterministic identity |
| `asset` | `str` | Acquired asset |
| `acquired_quantity` | `Decimal` | Original quantity acquired |
| `remaining_quantity` | `Decimal` | Quantity not yet consumed; must be `>= 0` |
| `unit_cost` | `Decimal` | Cost per unit in cost currency |
| `total_cost` | `Decimal` | `acquired_quantity * unit_cost` |
| `cost_currency` | `str` | Currency of cost |
| `acquired_timestamp` | `datetime` | Timezone-aware |
| `source_transaction_id` | `str` | Canonical transaction that created this lot |
| `acquisition_type` | `AcquisitionType` | BUY, SWAP_IN, DEPOSIT_KNOWN_COST, OTHER |
| `fee` | `Optional[Decimal]` | Fee paid at acquisition |
| `fee_asset` | `Optional[str]` | Asset in which acquisition fee was paid |
| `linked_event_id` | `str` | AccountingEvent that created this lot |

**Identity**: SHA-256 of `source_transaction_id`, `asset`, `acquired_quantity`, `unit_cost`, `acquired_timestamp`.

**Immutability**: Frozen. `remaining_quantity` is updated via new `LotConsumption` records, not by mutating the lot.

**Relationships**: Created by an `AccountingEvent`. Consumed by zero or more `LotConsumption` records.

---

### 2.3 LotConsumption

**Purpose**: Records a precise reduction of an acquisition lot by a disposal event, preserving full auditability.

**Fields**:
| Field | Type | Notes |
|---|---|---|
| `consumption_id` | `str` | Deterministic identity |
| `lot_id` | `str` | Acquisition lot being consumed |
| `disposal_event_id` | `str` | AccountingEvent that consumed this lot |
| `asset` | `str` | Asset being consumed |
| `quantity_consumed` | `Decimal` | Amount taken from the lot |
| `unit_cost` | `Decimal` | Cost per unit from the lot |
| `cost_allocated` | `Decimal` | `quantity_consumed * unit_cost` |
| `cost_currency` | `str` | Currency of cost |
| `disposal_proceeds` | `Optional[Decimal]` | Proceeds attributable to this consumption |
| `proceeds_currency` | `Optional[str]` | Currency of proceeds |
| `realized_pnl` | `Optional[Decimal]` | `disposal_proceeds - cost_allocated` (same currency) |
| `pnl_currency` | `Optional[str]` | Currency of P&L |
| `consumed_timestamp` | `datetime` | Timezone-aware; from disposal event |

**Identity**: SHA-256 of `lot_id`, `disposal_event_id`, `quantity_consumed`, `consumed_timestamp`.

**Immutability**: Frozen. Append-only.

**Relationships**: Links one `AcquisitionLot` to one `AccountingEvent` (disposal).

---

### 2.4 RealizedPnL

**Purpose**: Aggregated realized P&L by asset, period, or acquisition lot.

**Fields**:
| Field | Type | Notes |
|---|---|---|
| `pnl_id` | `str` | Deterministic identity |
| `asset` | `str` | Asset for which P&L is realized |
| `total_realized_pnl` | `Decimal` | Sum of all realized P&L for this asset |
| `currency` | `str` | Currency of P&L |
| `consumption_ids` | `List[str]` | LotConsumption records that produced this P&L |
| `lot_ids` | `List[str]` | Acquisition lots involved |
| `event_ids` | `List[str]` | Disposal events involved |
| `from_timestamp` | `datetime` | Period start |
| `to_timestamp` | `datetime` | Period end |

**Identity**: SHA-256 of `asset`, `currency`, `from_timestamp`, `to_timestamp`, sorted `consumption_ids`.

**Immutability**: Frozen.

---

### 2.5 AccountingWarning / AccountingException

**Purpose**: Non-fatal warnings and fatal errors produced during accounting.

**AccountingWarning** (non-fatal; processing continues):
| Field | Type |
|---|---|
| `warning_id` | `str` |
| `code` | `WarningCode` enum |
| `message` | `str` |
| `source_transaction_id` | `Optional[str]` |
| `context` | `Optional[Dict[str, Any]]` |

**WarningCode examples**:
- `MISSING_COST_BASIS`
- `MISSING_PROCEEDS`
- `INSUFFICIENT_LOTS`
- `UNRESOLVED_ASSET`
- `MISSING_QUOTE_ASSET`
- `MISSING_FEE_ASSET`
- `ZERO_QUANTITY_DISPOSAL`
- `PARTIAL_SWAP_VALUATION`
- `UNMATCHED_TRANSFER`

**AccountingException** (fatal; halts accounting for the affected scope):
| Field | Type |
|---|---|
| `exception_id` | `str` |
| `code` | `ExceptionCode` enum |
| `message` | `str` |
| `source_transaction_id` | `Optional[str]` |

**ExceptionCode examples**:
- `INSUFFICIENT_LOTS_FOR_DISPOSAL`
- `NEGATIVE_LOT_REMAINING`

---

### 2.6 AccountingResult

**Purpose**: Top-level output of the accounting engine.

**Fields**:
| Field | Type |
|---|---|
| `events` | `List[AccountingEvent]` |
| `lots` | `List[AcquisitionLot]` |
| `consumptions` | `List[LotConsumption]` |
| `realized_pnl` | `List[RealizedPnL]` |
| `warnings` | `List[AccountingWarning]` |
| `errors` | `List[AccountingException]` |
| `summary` | `AccountingSummary` |

**Immutability**: Frozen.

---

### 2.7 AccountingSummary

**Purpose**: Aggregated counts and totals.

**Fields**:
| Field | Type |
|---|---|
| `total_events` | `int` |
| `acquisition_events` | `int` |
| `disposal_events` | `int` |
| `transfer_events` | `int` |
| `swap_events` | `int` |
| `total_lots_created` | `int` |
| `total_lots_consumed` | `int` |
| `total_realized_pnl` | `Decimal` |
| `pnl_currency` | `Optional[str]` |
| `warnings_count` | `int` |
| `errors_count` | `int` |

---

## 3. Transaction → Accounting Semantics

### 3.1 TRADE (with Side.BUY)

- Creates an `AccountingEvent` of type `ACQUISITION`.
- Creates an `AcquisitionLot`.
- Cost basis = `value` if present; otherwise `quantity * price`.
- If `value` and `price` are both present, `value` takes precedence for cost basis; `price` is recorded in metadata.
- If neither `value` nor `price` is available, produces `MISSING_COST_BASIS` warning; lot is created with `unit_cost = None` (unknown).
- Fee treatment: see Section 7.

### 3.2 TRADE (with Side.SELL)

- Creates an `AccountingEvent` of type `DISPOSAL`.
- Consumes acquisition lots per the selected cost-basis method.
- Proceeds = `value` if present; otherwise `quantity * price`.
- If proceeds cannot be determined, produces `MISSING_PROCEEDS` warning; P&L is `None`.
- If insufficient lots are available, produces `INSUFFICIENT_LOTS` error; event is still recorded but `realized_pnl = None`.

### 3.3 DEPOSIT

- Creates an `AccountingEvent` of type `ACQUISITION`.
- Creates an `AcquisitionLot` with `acquisition_type = DEPOSIT_KNOWN_COST` or `DEPOSIT_UNKNOWN_COST`.
- If `value` or `price` is available, cost basis is determined.
- If cost is unknown, produces `MISSING_COST_BASIS` warning.
- Deposits do NOT create taxable disposals.

### 3.4 WITHDRAWAL

- Creates an `AccountingEvent` of type `DISPOSAL`.
- Withdrawal is treated as a disposal at `proceeds = 0` (or `None` if unknown).
- If cost basis is unknown, produces `MISSING_COST_BASIS` warning.
- Consumes lots per cost-basis method.
- If `value` or `price` is available and represents market value at withdrawal, that may be used as proceeds; otherwise proceeds = 0.
- Produces `WITHDRAWAL_NO_PROCEEDS` warning when proceeds = 0.

### 3.5 TRANSFER

- Creates an `AccountingEvent` of type `TRANSFER`.
- Does NOT create acquisition lots or disposals.
- If the transfer is matched by `TransferReconciler`, the event references both legs and preserves original lot linkage.
- If unmatched, produces `UNMATCHED_TRANSFER` warning.
- No P&L is produced.

### 3.6 SWAP

- Creates an `AccountingEvent` of type `SWAP`.
- The outgoing asset is treated as a DISPOSAL; the incoming asset is treated as an ACQUISITION.
- Disposal proceeds = market value of outgoing asset at swap time, if determinable from canonical data; otherwise `MISSING_PROCEEDS` warning and proceeds = `None`.
- Acquisition cost = disposal proceeds minus fees, or explicit input value if available.
- If the swap is a Coinbase Convert mapped from `TransactionType.SWAP`, the two SWAP events (outgoing and incoming) are linked via `linked_event_ids`.
- Binance Convert remains in the `UNKNOWN` type and is handled by `ConvertReconciler`; the accounting engine sees the matched `ConvertFinding` and treats it as a SWAP pair.
- Fee treatment: see Section 7.

### 3.7 UNKNOWN

- Creates an `AccountingEvent` of type `WARNING`.
- Produces `UNKNOWN_TRANSACTION_TYPE` warning.
- No lots are created or consumed.
- If the UNKNOWN transaction is part of a matched convert pair, it is reclassified as SWAP by the accounting engine (using `ConvertFinding`).

---

## 4. Cost-Basis Methods

### 4.1 Interface

```python
class CostBasisMethod(ABC):
    @abstractmethod
    def consume(
        self,
        lot_pool: List[AcquisitionLot],
        disposal_quantity: Decimal,
        disposal_timestamp: datetime,
    ) -> LotConsumptionPlan:
        ...
```

`LotConsumptionPlan` contains:
- `consumptions: List[LotConsumption]`
- `remaining_quantity: Decimal`
- `warnings: List[str]`
- `errors: List[str]`

### 4.2 Implementations

| Method | Description | Deterministic? | Notes |
|---|---|---|---|
| FIFO | First In, First Out | Yes | Default for M020. Simplest to audit. |
| LIFO | Last In, First Out | Yes | Requires reverse ordering. |
| HIFO | Highest In, First Out | Yes | Requires sorting by unit cost descending. |
| Specific Identification | Caller specifies exact lot IDs | Yes | Requires explicit lot IDs in configuration or transaction metadata. |

### 4.3 Recommended Initial Method

**FIFO** for M020 implementation.

Rationale:
- Simplest to implement correctly.
- Most intuitive audit trail (earliest lots consumed first).
- Matches natural expectation for crypto accounting.
- Deterministic and easy to test.
- LIFO and HIFO are mechanical variants of the same interface.

---

## 5. Lot Model

### 5.1 Fields (AcquisitionLot)

Defined in Section 2.2.

### 5.2 Invariants

- `remaining_quantity >= 0` at all times.
- `remaining_quantity <= acquired_quantity`.
- `unit_cost >= 0`.
- `total_cost = acquired_quantity * unit_cost`.
- `lot_id` is deterministic and stable.
- `remaining_quantity` is never mutated in place; it is derived from `acquired_quantity` minus the sum of `quantity_consumed` across all `LotConsumption` records for that lot.

### 5.3 Partial Consumption

Supported. A lot may be consumed by multiple disposal events over time.

Example:
```
Lot: 10 BTC @ $40,000
Disposal 1: 3 BTC consumed
  remaining = 7 BTC
Disposal 2: 5 BTC consumed
  remaining = 2 BTC
```

### 5.4 Consumption Preservation

All `LotConsumption` records are retained. A lot is never deleted. The accounting engine can always reconstruct `remaining_quantity` by summing consumptions.

---

## 6. Lot Consumption Model

### 6.1 Fields (LotConsumption)

Defined in Section 2.3.

### 6.2 Identity

Deterministic SHA-256 of `lot_id`, `disposal_event_id`, `quantity_consumed`, `consumed_timestamp`.

### 6.3 Partial Consumption Example

```
Lot A: 10 BTC @ $40,000 (total_cost = 400,000)

Disposal event D1: sell 3 BTC
  LotConsumption C1:
    lot_id = A
    quantity_consumed = 3
    unit_cost = 40000
    cost_allocated = 120,000
    disposal_proceeds = 180,000
    realized_pnl = 60,000

  Lot A remaining = 7 BTC (derived)

Disposal event D2: sell 5 BTC
  LotConsumption C2:
    lot_id = A
    quantity_consumed = 5
    unit_cost = 40000
    cost_allocated = 200,000
    disposal_proceeds = 300,000
    realized_pnl = 100,000

  Lot A remaining = 2 BTC (derived)
```

---

## 7. Fee Treatment

### 7.1 Principles

Fees are costs. They must be allocated to either the acquisition cost or the disposal proceeds, depending on the fee asset and the transaction type.

### 7.2 BUY (Acquisition)

- `fee_asset == quote_asset` (e.g., BNB fee on BTC/USDT trade):
  - Add fee to acquisition cost: `total_cost = (quantity * unit_price) + fee`.
  - `unit_cost` is adjusted accordingly.
- `fee_asset == asset` (e.g., BTC fee on BTC acquisition):
  - Reduce acquisition quantity: `effective_quantity = quantity - fee`.
  - `unit_cost` remains based on gross `quantity`; the fee reduces the economic amount received.
- `fee_asset` is a third asset:
  - Produce `THIRD_ASSET_FEE` warning.
  - Do not silently guess. The fee is recorded in the transaction metadata but does NOT alter the acquisition lot cost basis unless explicitly configured.

### 7.3 SELL (Disposal)

- `fee_asset == asset` (e.g., BTC fee on BTC sale):
  - Reduce disposal quantity: `effective_quantity = quantity - fee`.
  - Proceeds are based on `effective_quantity * price`.
  - The fee is also recorded as a separate `AccountingEvent` of type `FEE` if needed for P&L.
- `fee_asset == quote_asset` (e.g., USDT fee on BTC sale):
  - Reduce proceeds: `net_proceeds = gross_proceeds - fee`.
  - `realized_pnl = net_proceeds - cost_allocated`.
- `fee_asset` is a third asset:
  - Produce `THIRD_ASSET_FEE` warning.
  - Proceeds are gross; fee is recorded separately.

### 7.4 SWAP

- Fees reduce the effective proceeds of the outgoing asset or increase the effective cost of the incoming asset.
- If fee asset = outgoing asset: reduce disposal quantity.
- If fee asset = incoming asset: reduce acquisition quantity.
- If fee asset is third asset: record as separate fee event; do not silently allocate.

### 7.5 Missing Fee Asset

- If `fee` is present but `fee_asset` is missing, produce `MISSING_FEE_ASSET` warning.
- The fee amount is recorded but not allocated to any leg until the fee asset is resolved.

---

## 8. Transfer Treatment

### 8.1 Matched Internal Transfer

- Produces an `AccountingEvent` of type `TRANSFER`.
- Does NOT create or consume lots.
- The original acquisition lots remain linked to the source account.
- The receiving account does NOT create new lots with cost = 0.
- If the transfer is unmatched, produces `UNMATCHED_TRANSFER` warning and does not alter lots.

### 8.2 Cross-Account Transfer (External)

- If a transfer is between different sources/exchanges (not matched as internal), it is treated as a WITHDRAWAL from the source and a DEPOSIT to the destination.
- Each side is processed independently with its own cost basis.

---

## 9. Swap Treatment

### 9.1 Economic Definition

A swap is a simultaneous disposal of asset A and acquisition of asset B.

### 9.2 Accounting Events

- Two `AccountingEvent` records are created:
  - `DISPOSAL` for the outgoing asset.
  - `ACQUISITION` for the incoming asset.
- Both events share a common `swap_id` linking them.

### 9.3 Proceeds Determination

- If the canonical transaction includes `value` or `price` for the outgoing asset, that is used as proceeds.
- If the swap is reconstructed from two separate canonical transactions (e.g., Coinbase Convert producing two SWAP transactions), the outgoing transaction provides proceeds and the incoming transaction provides cost basis.
- If proceeds cannot be determined, produce `MISSING_PROCEEDS` warning; P&L is `None`.

### 9.4 Coinbase Convert

- Coinbase adapter produces two `TransactionType.SWAP` transactions (outgoing and incoming).
- The accounting engine treats them as a linked swap pair.
- If only one side is present, produces `PARTIAL_SWAP_VALUATION` warning.

### 9.5 Binance Convert

- `ConvertReconciler` produces a `ConvertFinding` linking the two legs.
- The accounting engine consumes the `ConvertFinding` and produces a single SWAP accounting event pair.
- If the convert finding is missing or incomplete, produces `MISSING_CONVERT_LINK` warning.

---

## 10. Missing-Data Policy

### 10.1 Principles

The engine must NEVER invent a cost basis, proceeds, or market value. Missing data produces explicit warnings or errors.

### 10.2 Warning Codes

| Code | Condition | Action |
|---|---|---|
| `MISSING_COST_BASIS` | Acquisition without price/value | Create lot with `unit_cost = None`; warn |
| `MISSING_PROCEEDS` | Disposal without price/value | Record disposal with `proceeds = None`; warn |
| `INSUFFICIENT_LOTS` | Disposal quantity exceeds available lots | Record partial disposal; error for remainder |
| `UNRESOLVED_ASSET` | Asset cannot be determined | Skip; error |
| `MISSING_QUOTE_ASSET` | Price present but quote asset missing | Record price; warn; do not alter lot |
| `MISSING_FEE_ASSET` | Fee present but fee asset missing | Record fee; warn; do not allocate |
| `ZERO_QUANTITY_DISPOSAL` | Disposal quantity = 0 | Skip; error |
| `PARTIAL_SWAP_VALUATION` | Swap with only one leg valued | Record what is known; warn |
| `UNMATCHED_TRANSFER` | Transfer not in TransferResult | Record transfer event; warn |
| `UNKNOWN_TRANSACTION_TYPE` | TransactionType.UNKNOWN not in reconciliation | Record warning event; skip |

### 10.3 Error Codes

| Code | Condition | Action |
|---|---|---|
| `INSUFFICIENT_LOTS_FOR_DISPOSAL` | Disposal quantity > sum of remaining lot quantities | Halt accounting for this disposal; record error |
| `NEGATIVE_LOT_REMAINING` | Derived remaining quantity < 0 | Halt; record error (data integrity violation) |

---

## 11. P&L Definitions

### 11.1 Cost Basis

```
cost_basis = sum of (quantity_consumed * unit_cost) for each lot consumed
```

- Always in the cost currency of the lots consumed.
- If lots have mixed cost currencies, produce `MIXED_COST_CURRENCIES` warning and normalize to a single reporting currency if configured.

### 11.2 Proceeds

```
proceeds = disposal_quantity * price  (or explicit value from transaction)
```

- Minus disposal fees in the quote asset.
- If fee is in the disposed asset, `effective_quantity = quantity - fee`, and proceeds = `effective_quantity * price`.

### 11.3 Realized Gain

```
realized_gain = proceeds - cost_basis
```

- Both in the same currency.
- If currencies differ, produce `CURRENCY_MISMATCH` warning and set `realized_pnl = None`.

### 11.4 Realized Loss

```
realized_loss = cost_basis - proceeds
```

- Same currency requirements as gain.

### 11.5 Realized P&L (signed)

```
realized_pnl = proceeds - cost_basis
```

- Positive = gain.
- Negative = loss.
- Zero = breakeven.

### 11.6 Unrealized Gain/Loss

**Out of scope for M020.** No live market pricing. Unrealized P&L requires a reliable market-price abstraction that does not currently exist.

---

## 12. Multi-Currency Policy

### 12.1 Cost Currency

- Each `AcquisitionLot` has a `cost_currency` derived from the `quote_asset` of the acquisition transaction.
- If `quote_asset` is missing, `cost_currency = None` and `unit_cost = None`.

### 12.2 Proceeds Currency

- Derived from the `quote_asset` of the disposal transaction.
- If missing, `proceeds_currency = None`.

### 12.3 Currency Matching

- P&L is only calculated when `cost_currency == proceeds_currency`.
- If currencies differ, produce `CURRENCY_MISMATCH` warning and set `realized_pnl = None`.

### 12.4 FX Normalization

**Out of scope for M020.** The engine does not convert between currencies. A future FX/valuation layer may normalize to a base reporting currency.

### 12.5 Base Reporting Currency

- Configurable in `AccountingConfiguration`.
- Used only for summary aggregation if all lots and disposals share that currency.
- If configured currency does not match lot currencies, produce `CURRENCY_MISMATCH` warning on summary.

---

## 13. Accounting Configuration

### 13.1 AccountingConfiguration

```python
class AccountingConfiguration(BaseModel):
    cost_basis_method: CostBasisMethod = FIFO()
    base_reporting_currency: Optional[str] = None
    timezone: str = "UTC"
    fee_allocation_policy: FeeAllocationPolicy = FeeAllocationPolicy.ADJUST_ACQUISITION_COST
    missing_cost_basis_policy: MissingCostBasisPolicy = MissingCostBasisPolicy.CREATE_LOT_WITH_NULL_COST
    transfer_preserves_lots: bool = True
    require_matching_transfer_for_lot_preservation: bool = True
```

### 13.2 Enums

**FeeAllocationPolicy**:
- `ADJUST_ACQUISITION_COST` — add fee to acquisition cost.
- `REDUCE_ACQUISITION_QUANTITY` — reduce acquired quantity.
- `RECORD_SEPARATE_FEE` — record as separate fee event.

**MissingCostBasisPolicy**:
- `CREATE_LOT_WITH_NULL_COST` — create lot but P&L is undefined until cost is known.
- `SKIP_ACQUISITION` — do not create lot; produce error.

### 13.3 No Hardcoding

- Accounting policy is injected via configuration.
- Adapters do not set accounting policy.
- Reconciliation results are inputs, not policy.

---

## 14. Determinism

### 14.1 Guarantees

Given identical:
- canonical transaction list (same order),
- reconciliation results (transfer matches, convert findings),
- accounting configuration,

the accounting engine must produce identical:
- `event_id` values,
- `lot_id` values,
- `consumption_id` values,
- `realized_pnl` values,
- warnings and errors (same codes, same order).

### 14.2 Mechanisms

- All identities are SHA-256 of stable, sorted inputs.
- Lot ordering within a consumption plan is deterministic (FIFO: by `acquired_timestamp` ascending; LIFO: descending; HIFO: by `unit_cost` descending).
- No `uuid4`, no `datetime.now()`, no `time.time()`.
- All timestamps come from canonical transactions.

### 14.3 Ordering Sensitivity

- The engine processes transactions in the order provided.
- For disposals that consume multiple lots, the cost-basis method determines order.
- For acquisitions, lot creation order follows transaction order.

---

## 15. Auditability

### 15.1 Traceability Chain

```
RealizedPnL
  → LotConsumption (one or more)
    → AcquisitionLot
      → AccountingEvent (ACQUISITION)
        → CanonicalTransaction (source)
```

Every P&L result can be traced to:
1. The disposal transaction.
2. The specific lots consumed.
3. The acquisition transactions that created those lots.

### 15.2 Metadata Preservation

- `AccountingEvent.metadata` includes:
  - `source_transaction_ids` (full list)
  - `adapter_warnings` (from the adapter)
  - `detector_confidence`
  - `reconciliation_match_id` (if from a transfer or convert match)

### 15.3 No Opaque Calculations

- `cost_allocated = quantity_consumed * unit_cost` is explicit in `LotConsumption`.
- `realized_pnl = disposal_proceeds - cost_allocated` is explicit in `LotConsumption`.
- `RealizedPnL` aggregates existing `LotConsumption` records; it does not recalculate from raw transactions.

---

## 16. Proposed Architecture

### 16.1 Directory Layout

```
backend/accounting/
  __init__.py
  models.py          # AccountingEvent, AcquisitionLot, LotConsumption, RealizedPnL, warnings, results
  engine.py          # AccountingEngine: orchestrates events, lots, consumption, P&L
  methods.py         # FIFO, LIFO, HIFO, SpecificIdentification
  fees.py            # Fee allocation policies
  transfers.py       # Transfer treatment (lot preservation)
  swaps.py           # Swap/conversion treatment
  configuration.py   # AccountingConfiguration
  exceptions.py      # AccountingWarning, AccountingException, codes
```

### 16.2 Dependency Rules

- `backend/accounting/` may import:
  - `backend/models/transaction.py`
  - `backend/reconciliation/duplicates.py`
  - `backend/reconciliation/transfers.py`
  - `backend/reconciliation/converts.py`
  - `backend/processing/comments.py`
- `backend/accounting/` MUST NOT import:
  - Any adapter (`backend/adapters/*`)
  - The detector (`backend/ingestion/detector.py`)
  - The reader (`backend/ingestion/reader.py`)

### 16.3 No Circular Imports

- `AccountingEngine` takes `List[CanonicalTransaction]`, `TransferResult`, `ConvertResult`, `CommentResult`, and `AccountingConfiguration` as inputs.
- It returns `AccountingResult`.
- The pipeline imports and calls the engine; the engine does not import the pipeline.

### 16.4 Minimal Abstraction

- No base classes beyond `CostBasisMethod` (one interface, four implementations).
- No event bus, no message queue, no database dependency.
- Pure in-memory calculation.

---

## 17. Pipeline Integration

### 17.1 Placement

Accounting runs AFTER all existing reconciliation and comment processing:

```
CSV
  → read_csv_safely
  → detect_exchange
  → adapter.adapt()
  → CanonicalTransaction[]
  → DuplicateDetector
  → TransferReconciler
  → ConvertReconciler
  → CommentEngine
  → AccountingEngine        <-- new
  → ProcessingResult + AccountingResult
```

### 17.2 Optionality

Accounting is opt-in via `AccountingConfiguration`. The existing `/api/v1/process` endpoint continues to return `ProcessingResult` unchanged when accounting is disabled.

When enabled, `ProcessingResult` is extended with an optional `accounting_result: Optional[AccountingResult]` field.

### 17.3 Backward Compatibility

- Existing API clients that do not request accounting see no change.
- New API clients can request accounting by passing `?accounting=true` or by using a new `/api/v1/account` endpoint (see Section 19).

---

## 18. API Boundary

### 18.1 Recommendation

**Do NOT fold accounting into `/api/v1/process` as the default response.**

Rationale:
- Accounting is computationally heavier than ingestion.
- It may be optional for some users.
- Separate endpoint allows independent versioning and caching.

### 18.2 Proposed Endpoint

```
POST /api/v1/account
```

**Request**: Same as `/api/v1/process` (file upload + timezone + optional accounting config JSON).

**Response**: `AccountingResult`.

**Alternative**: Add `?accounting=true` to `/api/v1/process` to include `accounting_result` in the existing `ProcessingResult`.

### 18.3 Response Structure

```json
{
  "events": [...],
  "lots": [...],
  "consumptions": [...],
  "realized_pnl": [...],
  "warnings": [...],
  "errors": [...],
  "summary": {
    "total_events": 12,
    "acquisition_events": 5,
    "disposal_events": 4,
    "transfer_events": 2,
    "swap_events": 1,
    "total_lots_created": 5,
    "total_lots_consumed": 3,
    "total_realized_pnl": "1500.00",
    "pnl_currency": "USD",
    "warnings_count": 0,
    "errors_count": 0
  }
}
```

---

## 19. Test Strategy

### 19.1 Basic Scenarios

| Test | Description |
|---|---|
| `test_single_buy_creates_lot` | One BUY produces one lot with correct cost basis |
| `test_single_sell_consumes_lot` | One SELL consumes one lot; P&L = proceeds - cost |
| `test_buy_then_sell` | BUY → SELL produces one acquisition event, one disposal event, one consumption, one P&L |
| `test_multiple_buys_then_sell_fifo` | Two BUYs at different prices; SELL consumes FIFO |
| `test_partial_lot_consumption` | Lot of 10; sell 3; remaining 7 |
| `test_complete_lot_consumption` | Lot of 10; sell 10; remaining 0 |
| `test_multiple_disposals` | Lot of 10; sell 3 then 5; remaining 2 |

### 19.2 Cost-Basis Methods

| Test | Method |
|---|---|
| `test_fifo_consumption` | FIFO: earliest lots first |
| `test_lifo_consumption` | LIFO: latest lots first |
| `test_hifo_consumption` | HIFO: highest unit cost first |
| `test_specific_identification` | Explicit lot IDs specified |

### 19.3 Fee Scenarios

| Test | Description |
|---|---|
| `test_quote_asset_fee_on_buy` | Fee in quote asset increases acquisition cost |
| `test_base_asset_fee_on_buy` | Fee in base asset reduces acquisition quantity |
| `test_third_asset_fee_on_buy` | Fee in unrelated asset produces warning |
| `test_quote_asset_fee_on_sell` | Fee in quote asset reduces proceeds |
| `test_base_asset_fee_on_sell` | Fee in base asset reduces disposal quantity |
| `test_swap_with_fee` | Swap with fee in outgoing asset reduces disposal quantity |

### 19.4 Transfer Scenarios

| Test | Description |
|---|---|
| `test_matched_internal_transfer_preserves_lots` | TransferMatch links lots; no new lots created |
| `test_unmatched_transfer_produces_warning` | Unmatched transfer generates warning |
| `test_transfer_followed_by_disposal` | Transfer then sell from receiving account preserves original cost |

### 19.5 Swap Scenarios

| Test | Description |
|---|---|
| `test_swap_creates_disposal_and_acquisition` | BTC → ETH produces disposal event + acquisition event |
| `test_swap_proceeds_from_canonical_value` | Swap with explicit value produces correct cost basis |
| `test_swap_missing_proceeds_produces_warning` | Swap without price/value produces MISSING_PROCEEDS |
| `test_coinbase_convert_swap_pair` | Two SWAP transactions linked as swap pair |
| `test_binance_convert_swap_pair` | ConvertFinding produces swap events |

### 19.6 Error Scenarios

| Test | Description |
|---|---|
| `test_insufficient_lots_for_disposal` | Disposal quantity > available lots |
| `test_missing_cost_basis_creates_warning` | Acquisition without price/value |
| `test_missing_proceeds_creates_warning` | Disposal without price/value |
| `test_zero_quantity_disposal_rejected` | Disposal with quantity = 0 |
| `test_negative_quantity_rejected` | Disposal with negative quantity |
| `test_missing_asset_rejected` | Transaction with empty asset |
| `test_missing_timestamp_rejected` | Transaction with naive timestamp |

### 19.7 Determinism

| Test | Description |
|---|---|
| `test_deterministic_lot_ids` | Same input produces identical lot IDs |
| `test_deterministic_consumption_ids` | Same input produces identical consumption IDs |
| `test_deterministic_pnl` | Same input produces identical P&L |
| `test_deterministic_warnings` | Same input produces identical warning codes and order |

### 19.8 Decimal Integrity

| Test | Description |
|---|---|
| `test_no_float_arithmetic_in_accounting` | All financial fields are Decimal; no float operations |
| `test_decimal_precision_preserved` | High-precision Decimals survive lot creation and consumption |

---

## 20. Explicit Non-Goals

M020 MUST NOT:

- Add another exchange adapter.
- Modify Binance or Coinbase parsing logic.
- Redesign the detector or registry.
- Implement unrealized P&L.
- Implement live market pricing or historical price lookups.
- Implement tax-jurisdiction-specific rules (e.g., 1031 like-kind, wash sale).
- Silently estimate missing cost basis.
- Invent or interpolate missing financial values.
- Mutate canonical transactions.
- Use floating-point arithmetic for financial quantities.
- Depend on external APIs for valuation.
- Implement database persistence (in-memory only for M020).

---

## 21. Implementation Order

### M020-A: Foundation (Models + Engine Skeleton)

1. `backend/accounting/models.py` — all domain models, enums, exceptions.
2. `backend/accounting/configuration.py` — `AccountingConfiguration`.
3. `backend/accounting/methods.py` — `CostBasisMethod` interface + FIFO implementation.
4. `backend/accounting/engine.py` — `AccountingEngine` class with `process()` method.
5. Unit tests for models and FIFO basic scenarios.

### M020-B: Fee + Transfer + Swap

6. `backend/accounting/fees.py` — fee allocation policies.
7. `backend/accounting/transfers.py` — transfer treatment.
8. `backend/accounting/swaps.py` — swap treatment.
9. Integration tests for fee scenarios, transfer scenarios, swap scenarios.

### M020-C: P&L + Summary + Pipeline Integration

10. `backend/accounting/engine.py` — `RealizedPnL` aggregation.
11. `backend/accounting/exceptions.py` — warning/error codes and formatting.
12. Pipeline integration: `ProcessingPipeline` optionally calls `AccountingEngine`.
13. API endpoint: `/api/v1/account` or `?accounting=true` on `/api/v1/process`.
14. Full regression suite update.

---

## 22. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Incomplete canonical data (missing price/value) | Medium | Explicit warnings; never invent values. |
| Multi-currency P&L complexity | Low | Defer FX normalization; require matching currencies for P&L. |
| Fee allocation ambiguity | Medium | Configurable policy; explicit warnings for third-asset fees. |
| Large lot histories (performance) | Low | FIFO/LIFO/HIFO are O(n log n) or O(n); specific ID is O(1). |
| Swap reconstruction from partial data | Medium | Require matched ConvertFinding or two SWAP transactions; warn otherwise. |
| Determinism under concurrent processing | Low | Engine is stateless per invocation; no global mutable state. |

---

## 23. Recommended M020-A Implementation Task

Implement the M020-A milestone:

1. Create `backend/accounting/models.py` with `AccountingEvent`, `AcquisitionLot`, `LotConsumption`, `RealizedPnL`, `AccountingWarning`, `AccountingException`, `AccountingResult`, `AccountingSummary`, and all supporting enums.
2. Create `backend/accounting/configuration.py` with `AccountingConfiguration`.
3. Create `backend/accounting/methods.py` with `CostBasisMethod` interface and `FIFO` implementation.
4. Create `backend/accounting/engine.py` with `AccountingEngine.process()` that:
   - Accepts `List[CanonicalTransaction]`, `TransferResult`, `ConvertResult`, `AccountingConfiguration`.
   - Produces `AccountingResult`.
   - Handles BUY, SELL, DEPOSIT, WITHDRAWAL, TRANSFER, SWAP, UNKNOWN per Section 3.
   - Creates lots for acquisitions, consumes lots for disposals.
   - Produces warnings for missing data.
5. Write unit tests for:
   - Model validation.
   - FIFO basic scenarios (buy, sell, partial consumption).
   - Determinism (identical input → identical output).
   - Decimal integrity (no floats).
6. Do NOT modify adapters, pipeline, or API in M020-A.

Deliverable: A clean, deterministic, test-driven accounting foundation ready for M020-B (fees, transfers, swaps) and M020-C (P&L, API integration).
