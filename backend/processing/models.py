from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from backend.accounting.models import AccountingResult
from backend.models.transaction import CanonicalTransaction
from backend.processing.comments import CommentResult
from backend.reconciliation.converts import ConvertResult
from backend.reconciliation.duplicates import DuplicateResult
from backend.reconciliation.transfers import TransferResult


class ProcessingSummary(BaseModel):
    total_transactions: int = 0
    duplicate_groups: int = 0
    exact_duplicates: int = 0
    probable_duplicates: int = 0
    possible_duplicates: int = 0
    internal_transfers: int = 0
    unknown_transactions: int = 0
    fees: int = 0
    deposits: int = 0
    withdrawals: int = 0
    transfers: int = 0
    trades: int = 0
    swaps: int = 0
    convert_events: int = 0
    unresolved_convert_rows: int = 0
    comments: int = 0
    acquisitions: int = 0
    disposals: int = 0
    non_accounting: int = 0
    unresolved: int = 0
    accounting_events: int = 0
    total_proceeds: Optional[str] = None
    total_cost_basis: Optional[str] = None
    total_fees: Optional[str] = None
    realized_gains: Optional[str] = None
    realized_losses: Optional[str] = None
    net_realized_pnl: Optional[str] = None


class ProcessingResult(BaseModel):
    source: Optional[str] = None
    report_type: Optional[str] = None
    transaction_count: int = 0
    transactions: List[CanonicalTransaction] = []
    duplicate_findings: Optional[DuplicateResult] = None
    transfer_matches: Optional[TransferResult] = None
    convert_matches: Optional[ConvertResult] = None
    comment_findings: Optional[CommentResult] = None
    warnings: List[str] = []
    errors: List[str] = []
    summary: ProcessingSummary = ProcessingSummary()
    accounting_result: Optional[AccountingResult] = None


ProcessingResult.model_rebuild()
