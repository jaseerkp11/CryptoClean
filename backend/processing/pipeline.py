from __future__ import annotations

import os
import tempfile
from decimal import Decimal
from typing import Optional

import pandas as pd

from backend.accounting.configuration import AccountingConfiguration
from backend.accounting.engine import AccountingEngine
from backend.accounting.models import AccountingEventType
from backend.ingestion.reader import read_csv_safely
from backend.ingestion.detector import detect_exchange
from backend.adapters.registry import get_adapter, AdapterNotFoundError
from backend.reconciliation.duplicates import (
    DuplicateDetector,
    DuplicateClassification,
)
from backend.reconciliation.transfers import TransferReconciler
from backend.reconciliation.converts import ConvertReconciler
from backend.models.transaction import TransactionType
from backend.processing.comments import CommentEngine
from backend.processing.models import ProcessingResult, ProcessingSummary
from backend.plans import get_plan_config, Plan


class ProcessingPipeline:
    def __init__(self, timestamp_tolerance_seconds: int = 1):
        if timestamp_tolerance_seconds < 0:
            raise ValueError("Timestamp tolerance must be non-negative.")
        self.timestamp_tolerance_seconds = timestamp_tolerance_seconds
        self.comment_engine = CommentEngine()

    def process_file(
        self,
        file_path: str,
        timezone: Optional[str] = None,
        accounting_config: Optional[AccountingConfiguration] = None,
        plan: str = Plan.FREE,
    ) -> ProcessingResult:
        result = ProcessingResult()
        plan_config = get_plan_config(plan)

        try:
            df, _row_count, _col_count, column_names, read_warnings = read_csv_safely(
                file_path
            )
        except ValueError as e:
            result.errors.append(str(e))
            return result

        if read_warnings:
            result.warnings.extend(read_warnings)

        try:
            exchange, report_type, _confidence, _indicators, detect_warnings = detect_exchange(
                file_path, df, column_names
            )
        except Exception as e:
            result.errors.append(f"Source detection failed: {e}")
            return result

        result.source = exchange
        result.report_type = report_type
        if detect_warnings:
            result.warnings.extend(detect_warnings)

        if exchange == "unknown":
            result.errors.append("Unsupported or unknown source: unknown")
            return result

        try:
            adapter_cls = get_adapter(exchange, report_type)
            adapter = adapter_cls(timezone)
        except AdapterNotFoundError as e:
            result.errors.append(str(e))
            return result
        except Exception as e:
            result.errors.append(f"Adapter initialization failed: {e}")
            return result

        working = df.copy()
        for col in working.columns:
            working[col] = working[col].apply(lambda x: "" if pd.isna(x) else str(x))
        rows = working.to_dict(orient="records")

        adapter_result = adapter.adapt(rows)
        result.warnings.extend(adapter_result.warnings)
        result.errors.extend(adapter_result.errors)
        transactions = adapter_result.transactions
        result.transactions = transactions
        result.transaction_count = len(transactions)

        plan_limit = plan_config.get("limit")
        if plan_limit is not None and len(transactions) > plan_limit:
            result.errors.append(
                f"This file contains {len(transactions)} transactions. "
                f"The {plan_config['name']} supports up to {plan_limit} transactions. "
                f"Choose a higher plan to process this file."
            )
            result.transactions = []
            result.transaction_count = 0
            return result

        if not transactions:
            return result

        dup_result = DuplicateDetector(self.timestamp_tolerance_seconds).detect(transactions)
        transfer_result = TransferReconciler(self.timestamp_tolerance_seconds).reconcile(
            transactions
        )
        convert_result = ConvertReconciler(self.timestamp_tolerance_seconds).reconcile(
            transactions
        )

        result.duplicate_findings = dup_result
        result.transfer_matches = transfer_result
        result.convert_matches = convert_result
        result.warnings.extend(convert_result.warnings)
        result.comment_findings = self.comment_engine.process(transactions)

        effective_accounting = accounting_config is not None or bool(plan_config.get("accounting"))
        if effective_accounting:
            try:
                engine = AccountingEngine(accounting_config or AccountingConfiguration())
                unique_ids = None
                if dup_result is not None:
                    unique_ids = set(dup_result.unique_transaction_ids)
                result.accounting_result = engine.process(
                    transactions=transactions,
                    transfer_result=transfer_result,
                    convert_result=convert_result,
                    comment_result=result.comment_findings,
                    unique_transaction_ids=unique_ids,
                )
            except Exception as e:
                result.errors.append(f"Accounting failed: {e}")

        result.summary = self._build_summary(
            transactions, dup_result, transfer_result, convert_result, result.comment_findings, result.accounting_result
        )

        return result

    def process_csv_content(
        self,
        content: str,
        timezone: Optional[str] = None,
        filename: str = "binance_export.csv",
        accounting_config: Optional[AccountingConfiguration] = None,
        plan: str = Plan.FREE,
    ) -> ProcessingResult:
        prefix = filename.replace(".csv", "_").replace(" ", "_")[:40]
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".csv",
            delete=False,
            newline="",
            encoding="utf-8",
            prefix=prefix,
        ) as tmp:
            tmp.write(content)
            path = tmp.name
        try:
            return self.process_file(path, timezone, accounting_config=accounting_config, plan=plan)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def _build_summary(self, transactions, dup_result, transfer_result, convert_result, comment_result=None, accounting_result=None) -> ProcessingSummary:
        s = ProcessingSummary()
        s.total_transactions = len(transactions)
        s.duplicate_groups = len(dup_result.groups)
        s.exact_duplicates = sum(
            1
            for g in dup_result.groups
            if g.classification == DuplicateClassification.EXACT_DUPLICATE
        )
        s.probable_duplicates = sum(
            1
            for g in dup_result.groups
            if g.classification == DuplicateClassification.PROBABLE_DUPLICATE
        )
        s.possible_duplicates = sum(
            1
            for g in dup_result.groups
            if g.classification == DuplicateClassification.POSSIBLE_DUPLICATE
        )
        s.internal_transfers = len(transfer_result.matches)
        s.convert_events = len(convert_result.matches)
        s.unresolved_convert_rows = len(convert_result.unresolved_leg_ids)
        for tx in transactions:
            t = tx.transaction_type
            if t == TransactionType.UNKNOWN:
                s.unknown_transactions += 1
            elif t == TransactionType.FEE:
                s.fees += 1
            elif t == TransactionType.DEPOSIT:
                s.deposits += 1
            elif t == TransactionType.WITHDRAWAL:
                s.withdrawals += 1
            elif t == TransactionType.TRANSFER:
                s.transfers += 1
            elif t == TransactionType.TRADE:
                s.trades += 1
            elif t == TransactionType.SWAP:
                s.swaps += 1
        if comment_result:
            s.comments = len(comment_result.comments)

        if accounting_result:
            s.accounting_events = len(accounting_result.events)
            s.acquisitions = sum(1 for e in accounting_result.events if e.event_type == AccountingEventType.ACQUISITION)
            s.disposals = sum(1 for e in accounting_result.events if e.event_type == AccountingEventType.DISPOSAL)
            s.non_accounting = sum(1 for e in accounting_result.events if e.event_type == AccountingEventType.NON_ACCOUNTING)

            total_proceeds = Decimal("0")
            total_cost_basis = Decimal("0")
            total_fees = Decimal("0")
            realized_gains = Decimal("0")
            realized_losses = Decimal("0")
            net_realized_pnl = Decimal("0")

            for e in accounting_result.events:
                if e.proceeds is not None:
                    total_proceeds += e.proceeds
                if e.cost_basis is not None:
                    total_cost_basis += e.cost_basis
                if e.fee is not None:
                    total_fees += e.fee
                if e.realized_pnl is not None:
                    net_realized_pnl += e.realized_pnl
                    if e.realized_pnl > 0:
                        realized_gains += e.realized_pnl
                    elif e.realized_pnl < 0:
                        realized_losses += e.realized_pnl

            s.total_proceeds = str(total_proceeds) if total_proceeds != 0 else None
            s.total_cost_basis = str(total_cost_basis) if total_cost_basis != 0 else None
            s.total_fees = str(total_fees) if total_fees != 0 else None
            s.realized_gains = str(realized_gains) if realized_gains != 0 else None
            s.realized_losses = str(realized_losses) if realized_losses != 0 else None
            s.net_realized_pnl = str(net_realized_pnl) if net_realized_pnl != 0 else None

        return s