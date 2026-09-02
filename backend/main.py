from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from decimal import Decimal
from typing import Dict, Optional, List, Set, Tuple
import os
import sys
import csv
import io
import zipfile
import tempfile
import logging
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.ingestion.reader import read_csv_safely, MAX_FILE_SIZE_BYTES
from backend.ingestion.detector import detect_exchange
from backend.accounting.configuration import AccountingConfiguration
from backend.accounting.models import AccountingEventType, AccountingResult
from backend.processing.pipeline import ProcessingPipeline
from backend.processing.models import ProcessingResult
from backend.models.transaction import Source, TransactionType
from backend.plans import get_plan_config, Plan, PLAN_CONFIG

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class IngestResponse(BaseModel):
    status: str
    filename: str
    exchange: str
    report_type: Optional[str] = None
    confidence: float
    rows: int
    columns: int
    column_names: List[str]
    warnings: List[str]


class ErrorResponse(BaseModel):
    detail: str


app = FastAPI(title="CryptoClean API", version="0.1.0")

cors_origins = os.getenv("CORS_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

pipeline = ProcessingPipeline()

_ALLOWED_CONTENT_TYPES = {"text/csv", "application/csv", "application/vnd.ms-excel"}


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Cache-Control"] = "no-store"
    return response


def _validate_content_type(content_type: Optional[str]) -> None:
    if not content_type:
        raise HTTPException(
            status_code=400,
            detail="Content-Type header is required.",
        )
    main_type = content_type.split(";")[0].strip().lower()
    if main_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid content type: {content_type}. Only CSV files are allowed.",
        )


@app.get("/health", response_model=HealthResponse)
async def health():
    return {"status": "ok", "service": "CryptoClean", "version": "0.1.0"}


@app.get("/api/v1/plans")
async def list_plans():
    return {"plans": PLAN_CONFIG}


@app.post("/api/v1/ingest", response_model=IngestResponse)
async def ingest_csv(request: Request, file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required.")

    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed.")

    if os.path.sep in file.filename or (os.path.altsep and os.path.altsep in file.filename):
        raise HTTPException(status_code=400, detail="Invalid filename.")

    _validate_content_type(file.content_type)

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="File is too large.")

    import tempfile
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
            total_size = 0
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MAX_FILE_SIZE_BYTES:
                    raise ValueError("File is too large.")
                tmp.write(chunk)
            tmp_path = tmp.name

        df, row_count, col_count, column_names, warnings = read_csv_safely(tmp_path)
        exchange, report_type, confidence, matched_indicators, detector_warnings = detect_exchange(
            filename=file.filename,
            df=df,
            column_names=column_names,
        )
        all_warnings = list(warnings) + list(detector_warnings)

        return {
            "status": "success",
            "filename": file.filename,
            "exchange": exchange,
            "report_type": report_type,
            "confidence": confidence,
            "rows": row_count,
            "columns": col_count,
            "column_names": column_names,
            "warnings": all_warnings,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error.")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


@app.post("/api/v1/process", response_model=ProcessingResult)
async def process_csv_endpoint(
    request: Request, file: UploadFile = File(...), timezone: Optional[str] = None, accounting: bool = False, plan: str = Plan.FREE
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required.")

    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed.")

    if os.path.sep in file.filename or (os.path.altsep and os.path.altsep in file.filename):
        raise HTTPException(status_code=400, detail="Invalid filename.")

    _validate_content_type(file.content_type)

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="File is too large.")

    import tempfile

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
            total_size = 0
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MAX_FILE_SIZE_BYTES:
                    raise ValueError("File is too large.")
                tmp.write(chunk)
            tmp_path = tmp.name

        accounting_config = AccountingConfiguration() if (accounting or get_plan_config(plan).get("accounting")) else None
        result = pipeline.process_file(tmp_path, timezone, accounting_config=accounting_config, plan=plan)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error.")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    if result.errors:
        if result.transaction_count == 0:
            raise HTTPException(status_code=400, detail="; ".join(result.errors))
        return JSONResponse(
            status_code=207,
            content=result.model_dump(mode="json"),
        )
    return result


@app.post("/api/v1/account")
async def account_csv_endpoint(
    request: Request, file: UploadFile = File(...), timezone: Optional[str] = None, plan: str = Plan.COMPLETE
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required.")

    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed.")

    if os.path.sep in file.filename or (os.path.altsep and os.path.altsep in file.filename):
        raise HTTPException(status_code=400, detail="Invalid filename.")

    _validate_content_type(file.content_type)

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="File is too large.")

    import tempfile

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
            total_size = 0
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MAX_FILE_SIZE_BYTES:
                    raise ValueError("File is too large.")
                tmp.write(chunk)
            tmp_path = tmp.name

        result = pipeline.process_file(tmp_path, timezone, accounting_config=AccountingConfiguration(), plan=plan)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error.")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    if result.errors:
        if result.transaction_count == 0:
            raise HTTPException(status_code=400, detail="; ".join(result.errors))
        return JSONResponse(
            status_code=207,
            content=result.model_dump(mode="json"),
        )
    return result


class TaxYearReport(BaseModel):
    tax_year: str
    total_transactions: int = 0
    acquisitions: int = 0
    disposals: int = 0
    transfers: int = 0
    fees: int = 0
    income: int = 0
    total_proceeds: Optional[str] = None
    total_cost_basis: Optional[str] = None
    total_fees: Optional[str] = None
    realized_gains: Optional[str] = None
    realized_losses: Optional[str] = None
    net_realized_pnl: Optional[str] = None
    exceptions: int = 0
    warnings: List[str] = []


@app.post("/api/v1/tax-year", response_model=TaxYearReport)
async def tax_year_report(
    request: Request,
    file: UploadFile = File(...),
    timezone: Optional[str] = None,
    tax_year: str = "all",
    plan: str = Plan.STANDARD,
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required.")

    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed.")

    if os.path.sep in file.filename or (os.path.altsep and os.path.altsep in file.filename):
        raise HTTPException(status_code=400, detail="Invalid filename.")

    _validate_content_type(file.content_type)

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="File is too large.")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
            total_size = 0
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MAX_FILE_SIZE_BYTES:
                    raise ValueError("File is too large.")
                tmp.write(chunk)
            tmp_path = tmp.name

        result = pipeline.process_file(tmp_path, timezone, plan=plan)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error.")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    if result.errors and result.transaction_count == 0:
        raise HTTPException(status_code=400, detail="; ".join(result.errors))

    tx_map = {tx.transaction_id: tx for tx in result.transactions}

    def in_tax_year(tx):
        if tax_year == "all":
            return True
        if tx.timestamp:
            return str(tx.timestamp.year) == tax_year
        return False

    filtered_txs = [tx for tx in result.transactions if in_tax_year(tx)]

    acct = result.accounting_result
    acct_events = acct.events if acct else []

    filtered_event_ids = set()
    for event in acct_events:
        for tid in event.source_transaction_ids:
            tx = tx_map.get(tid)
            if tx and in_tax_year(tx):
                filtered_event_ids.add(event.event_id)
                break

    filtered_events = [e for e in acct_events if e.event_id in filtered_event_ids]

    acquisitions = sum(1 for e in filtered_events if e.event_type == AccountingEventType.ACQUISITION)
    disposals = [e for e in filtered_events if e.event_type == AccountingEventType.DISPOSAL]
    transfers = sum(1 for e in filtered_events if e.event_type == AccountingEventType.TRANSFER)
    fees = sum(1 for e in filtered_events if e.event_type == AccountingEventType.FEE)

    income_types = {"DEPOSIT_KNOWN_COST", "DEPOSIT_UNKNOWN_COST", "REWARD", "AIRDROP", "STAKING_REWARD", "CASH_VOUCHER", "COMMISSION_REBATE", "REFERRER_COMMISSION"}
    income = sum(1 for e in filtered_events if e.event_type == AccountingEventType.ACQUISITION and (e.metadata or {}).get("acquisition_type") in income_types)

    total_proceeds = Decimal("0")
    total_cost_basis = Decimal("0")
    total_fees = Decimal("0")
    realized_gains = Decimal("0")
    realized_losses = Decimal("0")
    net_realized_pnl = Decimal("0")

    for e in disposals:
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

    warnings = list(result.warnings)
    if acct:
        warnings.extend(w.message for w in acct.warnings)

    exceptions = sum(1 for tx in filtered_txs if tx.transaction_type == TransactionType.UNKNOWN)

    return TaxYearReport(
        tax_year=tax_year,
        total_transactions=len(filtered_txs),
        acquisitions=acquisitions,
        disposals=len(disposals),
        transfers=transfers,
        fees=fees,
        income=income,
        total_proceeds=str(total_proceeds) if total_proceeds is not None else None,
        total_cost_basis=str(total_cost_basis) if total_cost_basis is not None else None,
        total_fees=str(total_fees) if total_fees is not None else None,
        realized_gains=str(realized_gains) if realized_gains is not None else None,
        realized_losses=str(realized_losses) if realized_losses is not None else None,
        net_realized_pnl=str(net_realized_pnl) if net_realized_pnl is not None else None,
        exceptions=exceptions,
        warnings=warnings[:20],
    )


def _generate_pdf_report(result: ProcessingResult, tax_year: str = "all") -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    def add_section_title(title):
        pdf.ln(8)
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(30, 41, 59)
        pdf.cell(0, 8, title, ln=True)
        pdf.set_draw_color(203, 213, 225)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(2)

    def add_kv(key, value):
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(71, 85, 105)
        pdf.cell(60, 6, key, ln=0)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(0, 6, str(value) if value is not None else "UNRESOLVED", ln=1)

    # Cover
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 24)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 12, "KRYPTLEDG", ln=True, align="C")
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(71, 85, 105)
    pdf.cell(0, 8, "Crypto Accounting & Tax-Ready Report", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Helvetica", "", 10)
    add_kv("Generated:", datetime.now().strftime("%Y-%m-%d %H:%M UTC"))
    add_kv("Exchange:", result.source or "Unknown")
    add_kv("Report Type:", result.report_type or "Unknown")
    add_kv("Plan:", "Complete")
    add_kv("Tax Year:", tax_year if tax_year != "all" else "All Years")
    add_kv("Total Transactions:", result.transaction_count)

    # Executive Summary
    pdf.add_page()
    add_section_title("Executive Summary")
    s = result.summary
    add_kv("Total Transactions:", s.total_transactions)
    add_kv("Deposits:", s.deposits)
    add_kv("Withdrawals:", s.withdrawals)
    add_kv("Trades:", s.trades)
    add_kv("Transfers:", s.transfers)
    add_kv("Fees:", s.fees)
    add_kv("UNKNOWN / Unresolved:", s.unknown_transactions)
    add_kv("Duplicate Groups:", s.duplicate_groups)
    add_kv("Matched Transfers:", s.internal_transfers)
    add_kv("Convert Events:", s.convert_events)

    if result.accounting_result and result.accounting_result.summary:
        ars = result.accounting_result.summary
        add_kv("Accounting Events:", ars.total_events)
        add_kv("Acquisitions:", ars.acquisition_events)
        add_kv("Disposals:", ars.disposal_events)
        add_kv("Lots Created:", ars.total_lots_created)
        add_kv("Lots Consumed:", ars.total_lots_consumed)
        add_kv("Realized P&L:", str(ars.total_realized_pnl) if ars.total_realized_pnl is not None else "UNRESOLVED")
        add_kv("Accounting Warnings:", ars.warnings_count)
        add_kv("Accounting Errors:", ars.errors_count)

    # Transaction Summary
    add_section_title("Transaction Summary")
    tx_map = {tx.transaction_id: tx for tx in result.transactions}
    for tx in result.transactions[:50]:
        meta = tx.metadata or {}
        source_op = meta.get("source_operation", "")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(71, 85, 105)
        pdf.cell(60, 5, str(tx.timestamp)[:19] if tx.timestamp else "", ln=0)
        pdf.cell(30, 5, tx.transaction_type.value, ln=0)
        pdf.cell(20, 5, tx.asset, ln=0)
        pdf.cell(25, 5, str(tx.quantity), ln=0)
        pdf.cell(30, 5, source_op[:25], ln=1)
    if len(result.transactions) > 50:
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(0, 6, f"... and {len(result.transactions) - 50} more transactions", ln=True)

    # Reconciliation
    add_section_title("Reconciliation")
    if result.transfer_matches:
        add_kv("Matched Transfers:", len(result.transfer_matches.matches))
        add_kv("Unmatched Transfer Legs:", len(result.transfer_matches.unmatched_leg_ids))
    else:
        add_kv("Matched Transfers:", 0)

    if result.convert_matches:
        add_kv("Convert Matches:", len(result.convert_matches.matches))
    else:
        add_kv("Convert Matches:", 0)

    add_kv("Duplicate Groups:", len(result.duplicate_findings.groups) if result.duplicate_findings else 0)

    # Realized P&L
    add_section_title("Realized P&L")
    if result.accounting_result and result.accounting_result.realized_pnl:
        for pnl in result.accounting_result.realized_pnl:
            add_kv(f"P&L {pnl.asset}:", f"{pnl.total_realized_pnl} {pnl.currency}")
    else:
        add_kv("Realized P&L:", "UNRESOLVED - Cost basis could not be established from source data")

    # FIFO Lots
    add_section_title("FIFO Cost Basis")
    if result.accounting_result:
        add_kv("Total Lots:", len(result.accounting_result.lots))
        add_kv("Total Consumptions:", len(result.accounting_result.consumptions))
        for lot in result.accounting_result.lots[:20]:
            add_kv(f"Lot {lot.lot_id[:8]}:", f"{lot.asset} qty={lot.remaining_quantity} cost={lot.unit_cost}")
        if len(result.accounting_result.lots) > 20:
            pdf.set_font("Helvetica", "I", 9)
            pdf.cell(0, 6, f"... and {len(result.accounting_result.lots) - 20} more lots", ln=True)
    else:
        add_kv("FIFO Lots:", "No accounting data available")

    # Income
    add_section_title("Income")
    if result.accounting_result:
        income_events = [e for e in result.accounting_result.events if e.event_type == AccountingEventType.ACQUISITION]
        income_count = sum(1 for e in income_events if (e.metadata or {}).get("acquisition_type") in {
            "DEPOSIT_KNOWN_COST", "DEPOSIT_UNKNOWN_COST", "REWARD", "AIRDROP", "STAKING_REWARD", "CASH_VOUCHER", "COMMISSION_REBATE", "REFERRER_COMMISSION"
        })
        add_kv("Income Events:", income_count)
        for event in income_events[:10]:
            if (event.metadata or {}).get("acquisition_type") in {
                "DEPOSIT_KNOWN_COST", "DEPOSIT_UNKNOWN_COST", "REWARD", "AIRDROP", "STAKING_REWARD", "CASH_VOUCHER", "COMMISSION_REBATE", "REFERRER_COMMISSION"
            }:
                add_kv(f"  {event.asset}:", f"qty={event.quantity} cost_basis={event.cost_basis}")
    else:
        add_kv("Income:", "No accounting data available")

    # Capital Gains
    add_section_title("Capital Gains")
    if result.accounting_result:
        disposal_events = [e for e in result.accounting_result.events if e.event_type == AccountingEventType.DISPOSAL]
        add_kv("Total Disposals:", len(disposal_events))
        add_kv("Disposals with Proceeds:", sum(1 for e in disposal_events if e.proceeds is not None))
        add_kv("Disposals with Cost Basis:", sum(1 for e in disposal_events if e.cost_basis is not None))
        add_kv("Disposals with Realized P&L:", sum(1 for e in disposal_events if e.realized_pnl is not None))
    else:
        add_kv("Capital Gains:", "No accounting data available")

    # Missing Cost Basis
    add_section_title("Missing Cost Basis")
    if result.accounting_result:
        missing = [e for e in result.accounting_result.events if (
            (e.event_type == AccountingEventType.ACQUISITION and e.cost_basis is None) or
            (e.event_type == AccountingEventType.DISPOSAL and e.proceeds is None)
        )]
        add_kv("Unresolved Events:", len(missing))
        for event in missing[:10]:
            add_kv(f"  {event.asset}:", f"qty={event.quantity} type={event.event_type.value}")
    else:
        add_kv("Missing Cost Basis:", "No accounting data available")

    # Exceptions
    add_section_title("Exceptions & Review Required")
    exceptions = [tx for tx in result.transactions if tx.transaction_type == TransactionType.UNKNOWN]
    add_kv("UNKNOWN Transactions:", len(exceptions))
    for tx in exceptions[:10]:
        meta = tx.metadata or {}
        add_kv(f"  {tx.transaction_id[:12]}:", f"{meta.get('source_operation', '')} - {tx.asset}")
    if len(exceptions) > 10:
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(0, 6, f"... and {len(exceptions) - 10} more exceptions", ln=True)

    # Audit Trail Summary
    add_section_title("Audit Trail Summary")
    add_kv("Source Transactions:", len(result.transactions))
    add_kv("Canonical Transactions:", len(result.transactions))
    add_kv("Duplicate Groups:", len(result.duplicate_findings.groups) if result.duplicate_findings else 0)
    add_kv("Transfer Matches:", len(result.transfer_matches.matches) if result.transfer_matches else 0)
    add_kv("Convert Matches:", len(result.convert_matches.matches) if result.convert_matches else 0)
    add_kv("Accounting Events:", len(result.accounting_result.events) if result.accounting_result else 0)
    add_kv("FIFO Lots:", len(result.accounting_result.lots) if result.accounting_result else 0)

    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 6, "This report is prepared for tax reporting / review. It is not an official government tax form.", ln=True, align="C")
    pdf.cell(0, 6, "Generated by KryptLedg - Crypto Accounting & Tax-Ready Reporting", ln=True, align="C")

    return pdf.output()


@app.post("/api/v1/report/pdf")
async def generate_pdf_report(
    request: Request,
    file: UploadFile = File(...),
    timezone: Optional[str] = None,
    tax_year: str = "all",
    plan: str = Plan.COMPLETE,
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required.")

    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed.")

    if os.path.sep in file.filename or (os.path.altsep and os.path.altsep in file.filename):
        raise HTTPException(status_code=400, detail="Invalid filename.")

    _validate_content_type(file.content_type)

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="File is too large.")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
            total_size = 0
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MAX_FILE_SIZE_BYTES:
                    raise ValueError("File is too large.")
                tmp.write(chunk)
            tmp_path = tmp.name

        result = pipeline.process_file(tmp_path, timezone, plan=plan)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error.")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    if result.errors and result.transaction_count == 0:
        raise HTTPException(status_code=400, detail="; ".join(result.errors))

    try:
        pdf_bytes = _generate_pdf_report(result, tax_year)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to generate PDF report.")

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=KryptLedg_Report.pdf"},
    )


@app.post("/api/v1/export")
async def export_csv(
    request: Request,
    file: UploadFile = File(...),
    timezone: Optional[str] = None,
    plan: str = Plan.FREE,
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required.")

    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are allowed.")

    if os.path.sep in file.filename or (os.path.altsep and os.path.altsep in file.filename):
        raise HTTPException(status_code=400, detail="Invalid filename.")

    _validate_content_type(file.content_type)

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="File is too large.")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
            total_size = 0
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MAX_FILE_SIZE_BYTES:
                    raise ValueError("File is too large.")
                tmp.write(chunk)
            tmp_path = tmp.name

        result = pipeline.process_file(tmp_path, timezone, plan=plan)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error.")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    if result.errors and result.transaction_count == 0:
        raise HTTPException(status_code=400, detail="; ".join(result.errors))

    plan_config = get_plan_config(plan)
    is_complete = plan == Plan.COMPLETE
    is_standard = plan == Plan.STANDARD

    if plan == Plan.FREE:
        csv_content = _build_transaction_ledger(result)
        return StreamingResponse(
            io.StringIO(csv_content),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=transactions.csv"},
        )

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Transactions.csv", _build_transaction_ledger(result))
        zf.writestr("Accounting.csv", _build_accounting_report(result))
        zf.writestr("Transfers.csv", _build_transfer_reconciliation(result))
        zf.writestr("Exceptions.csv", _build_exceptions_review(result))
        zf.writestr("Summary.csv", _build_summary(result))
        zf.writestr("Audit_Trail.csv", _build_audit_trail(result))

        if plan == Plan.COMPLETE:
            zf.writestr("Detailed_Realized_PnL.csv", _build_detailed_pnl(result))
            zf.writestr("Holdings.csv", _build_holdings(result))
            zf.writestr("Missing_Cost_Basis.csv", _build_missing_cost_basis(result))

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=KryptLedg_Report.zip"},
    )


def _build_transaction_ledger(result: ProcessingResult) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    headers = [
        "transaction_id",
        "timestamp",
        "transaction_type",
        "side",
        "asset",
        "quantity",
        "source_transaction_id",
        "fee",
        "fee_asset",
        "wallet",
        "counterparty",
        "tx_hash",
        "confidence",
        "notes",
        "source_operation",
        "source_account",
        "source_change_signed",
        "source_remark",
        "classification",
        "classification_reason",
        "review_required",
    ]
    writer.writerow(headers)

    for tx in result.transactions:
        meta = tx.metadata or {}
        source_op = meta.get("source_operation", "")
        source_account = meta.get("source_account", "")
        source_change = meta.get("source_change_signed", "")
        source_remark = meta.get("source_remark", "")
        classification_reason = meta.get("classification_reason", "")

        review_required = "Yes" if tx.transaction_type == TransactionType.UNKNOWN else "No"

        writer.writerow([
            tx.transaction_id,
            tx.timestamp.isoformat() if tx.timestamp else "",
            tx.transaction_type.value if tx.transaction_type else "UNKNOWN",
            tx.side.value if tx.side else "",
            tx.asset,
            str(tx.quantity),
            tx.source_transaction_id or "",
            str(tx.fee) if tx.fee is not None else "",
            tx.fee_asset or "",
            tx.wallet or "",
            tx.counterparty or "",
            tx.tx_hash or "",
            str(tx.confidence),
            tx.notes or "",
            source_op,
            source_account,
            source_change,
            source_remark,
            tx.transaction_type.value if tx.transaction_type else "UNKNOWN",
            classification_reason,
            review_required,
        ])

    return output.getvalue()


def _build_accounting_report(result: ProcessingResult) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    headers = [
        "accounting_event_id",
        "date",
        "source_transaction_id",
        "exchange",
        "event_type",
        "asset",
        "quantity",
        "proceeds",
        "cost_basis",
        "fee",
        "fee_asset",
        "realized_pnl",
        "realized_gain",
        "realized_loss",
        "net_realized_pnl",
        "fifo_lot_reference",
        "classification",
        "classification_reason",
        "accounting_status",
        "review_required",
    ]
    writer.writerow(headers)

    if not result.accounting_result:
        writer.writerow(["No accounting data available", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""])
        return output.getvalue()

    tx_map = {tx.transaction_id: tx for tx in result.transactions}
    acct_lot_map: Dict[str, str] = {}
    for lot in result.accounting_result.lots:
        acct_lot_map[lot.source_transaction_id] = lot.lot_id

    consumption_pnl_map: Dict[str, Decimal] = {}
    if result.accounting_result.consumptions:
        for c in result.accounting_result.consumptions:
            if c.realized_pnl is not None:
                consumption_pnl_map[c.disposal_event_id] = consumption_pnl_map.get(c.disposal_event_id, Decimal("0")) + c.realized_pnl

    all_warnings = list(result.warnings)
    if result.accounting_result:
        all_warnings.extend(w.message for w in result.accounting_result.warnings)

    for event in result.accounting_result.events:
        source_tx_id = event.source_transaction_ids[0] if event.source_transaction_ids else ""
        tx = tx_map.get(source_tx_id)
        meta = tx.metadata if tx else {}
        source_op = meta.get("source_operation", "") if meta else ""
        classification_reason = meta.get("classification_reason", "") if meta else ""

        realized_pnl = event.realized_pnl
        if realized_pnl is None:
            realized_pnl = consumption_pnl_map.get(event.event_id)
        realized_gain = ""
        realized_loss = ""
        if realized_pnl is not None:
            if realized_pnl > 0:
                realized_gain = str(realized_pnl)
            elif realized_pnl < 0:
                realized_loss = str(realized_pnl)

        lot_refs = ";".join(event.linked_lot_ids) if event.linked_lot_ids else ""
        if not lot_refs and source_tx_id in acct_lot_map:
            lot_refs = acct_lot_map[source_tx_id]

        accounting_status = "accounted"
        review_required = "No"
        if event.event_type == AccountingEventType.NON_ACCOUNTING:
            accounting_status = "non-accounting"
            review_required = "Yes"

        tx_warnings = [w for w in all_warnings if source_tx_id in w or (source_op and source_op in w)]
        warning_str = "; ".join(tx_warnings) if tx_warnings else ""

        writer.writerow([
            event.event_id,
            event.timestamp.isoformat() if event.timestamp else "",
            source_tx_id,
            tx.source.value if tx and isinstance(tx.source, Source) else "",
            event.event_type.value,
            event.asset,
            str(event.quantity),
            str(event.proceeds) if event.proceeds is not None else "",
            str(event.cost_basis) if event.cost_basis is not None else "",
            str(event.fee) if event.fee is not None else "",
            event.fee_asset or "",
            str(realized_pnl) if realized_pnl is not None else "",
            realized_gain,
            realized_loss,
            str(realized_pnl) if realized_pnl is not None else "",
            lot_refs,
            tx.transaction_type.value if tx else "UNKNOWN",
            classification_reason,
            accounting_status,
            review_required,
        ])

    return output.getvalue()


def _build_transfer_reconciliation(result: ProcessingResult) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    headers = [
        "transfer_id",
        "source_transaction_id",
        "destination_transaction_id",
        "exchange",
        "asset",
        "quantity",
        "source_wallet",
        "destination_wallet",
        "source_timestamp",
        "destination_timestamp",
        "timestamp_difference",
        "matching_reason",
        "matching_status",
        "confidence",
        "accounting_treatment",
    ]
    writer.writerow(headers)

    if not result.transfer_matches:
        writer.writerow(["No transfer data available", "", "", "", "", "", "", "", "", "", "", "", "", "", ""])
        return output.getvalue()

    tx_map = {tx.transaction_id: tx for tx in result.transactions}

    for match in result.transfer_matches.matches:
        src_tx = tx_map.get(match.source_transaction_id)
        dst_tx = tx_map.get(match.destination_transaction_id)
        delta = abs((src_tx.timestamp - dst_tx.timestamp).total_seconds()) if src_tx and dst_tx and src_tx.timestamp and dst_tx.timestamp else 0

        writer.writerow([
            match.transfer_id,
            match.source_transaction_id,
            match.destination_transaction_id,
            src_tx.source.value if src_tx and isinstance(src_tx.source, Source) else "",
            match.asset,
            str(match.quantity),
            src_tx.wallet if src_tx else "",
            dst_tx.wallet if dst_tx else "",
            src_tx.timestamp.isoformat() if src_tx and src_tx.timestamp else "",
            dst_tx.timestamp.isoformat() if dst_tx and dst_tx.timestamp else "",
            str(int(round(delta))),
            "; ".join(match.reasons),
            "matched",
            str(match.confidence),
            "Internal transfer - no P&L impact",
        ])

    for tx_id in result.transfer_matches.unmatched_leg_ids:
        tx = tx_map.get(tx_id)
        if tx:
            writer.writerow([
                "",
                tx_id,
                "",
                tx.source.value if isinstance(tx.source, Source) else str(tx.source),
                tx.asset,
                str(tx.quantity),
                tx.wallet or "",
                "",
                tx.timestamp.isoformat() if tx.timestamp else "",
                "",
                "",
                "Unmatched transfer leg",
                "unmatched",
                "0",
                "Review required",
            ])

    return output.getvalue()


def _build_exceptions_review(result: ProcessingResult) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    headers = [
        "category",
        "source_exchange",
        "source_row",
        "original_operation",
        "transaction_id",
        "reference_id",
        "date",
        "asset",
        "quantity",
        "price",
        "value",
        "fee",
        "fee_asset",
        "wallet",
        "classification",
        "classification_reason",
        "accounting_status",
        "warning",
        "review_required",
    ]
    writer.writerow(headers)

    non_accounting_ids: Set[str] = set()
    if result.accounting_result:
        for event in result.accounting_result.events:
            if event.event_type == AccountingEventType.NON_ACCOUNTING:
                non_accounting_ids.update(event.source_transaction_ids)

    for tx in result.transactions:
        meta = tx.metadata or {}
        source_op = meta.get("source_operation", "")
        source_account = meta.get("source_account", "")
        source_change = meta.get("source_change_signed", "")
        source_remark = meta.get("source_remark", "")
        classification_reason = meta.get("classification_reason", "")

        is_adapter_exception = tx.transaction_type == TransactionType.UNKNOWN
        is_accounting_exception = tx.transaction_id in non_accounting_ids

        if not is_adapter_exception and not is_accounting_exception:
            continue

        category = "adapter" if is_adapter_exception else "accounting"

        acct_status = "accounted"
        if result.accounting_result:
            accounted = any(tx.transaction_id in e.source_transaction_ids for e in result.accounting_result.events)
            acct_status = "accounted" if accounted else "non-accounting"

        all_warnings = list(result.warnings)
        if result.accounting_result:
            all_warnings.extend(w.message for w in result.accounting_result.warnings)
        tx_warnings = [w for w in all_warnings if tx.transaction_id in w or (source_op and source_op in w)]
        warning_str = "; ".join(tx_warnings) if tx_warnings else classification_reason

        review_required = "Yes" if tx.transaction_type == TransactionType.UNKNOWN or acct_status == "non-accounting" else "No"

        source_row = f"{tx.timestamp.isoformat() if tx.timestamp else ''} | {source_account} | {source_op} | {tx.asset} | {source_change} | {source_remark}"

        writer.writerow([
            category,
            tx.source.value if isinstance(tx.source, Source) else str(tx.source),
            source_row,
            source_op,
            tx.transaction_id,
            tx.source_transaction_id or "",
            tx.timestamp.isoformat() if tx.timestamp else "",
            tx.asset,
            str(tx.quantity),
            str(tx.price) if tx.price is not None else "",
            str(tx.value) if tx.value is not None else "",
            str(tx.fee) if tx.fee is not None else "",
            tx.fee_asset or "",
            tx.wallet or source_account,
            tx.transaction_type.value if tx.transaction_type else "UNKNOWN",
            classification_reason,
            acct_status,
            warning_str,
            review_required,
        ])

    return output.getvalue()


def _build_summary(result: ProcessingResult) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["metric", "value"])

    s = result.summary
    writer.writerow(["total_transactions", s.total_transactions])
    writer.writerow(["deposits", s.deposits])
    writer.writerow(["withdrawals", s.withdrawals])
    writer.writerow(["transfers", s.transfers])
    writer.writerow(["trades", s.trades])
    writer.writerow(["fees", s.fees])
    writer.writerow(["unknown_transactions", s.unknown_transactions])
    writer.writerow(["duplicate_groups", s.duplicate_groups])
    writer.writerow(["exact_duplicates", s.exact_duplicates])
    writer.writerow(["probable_duplicates", s.probable_duplicates])
    writer.writerow(["possible_duplicates", s.possible_duplicates])
    writer.writerow(["matched_transfers", s.internal_transfers])
    writer.writerow(["convert_events", s.convert_events])
    writer.writerow(["unresolved_convert_rows", s.unresolved_convert_rows])
    writer.writerow(["comments", s.comments])

    if result.accounting_result and result.accounting_result.summary:
        ars = result.accounting_result.summary
        writer.writerow(["accounting_events", ars.total_events])
        writer.writerow(["acquisitions", ars.acquisition_events])
        writer.writerow(["disposals", ars.disposal_events])
        writer.writerow(["transfer_events", ars.transfer_events])
        writer.writerow(["swap_events", ars.swap_events])
        writer.writerow(["lots_created", ars.total_lots_created])
        writer.writerow(["lots_consumed", ars.total_lots_consumed])
        writer.writerow(["realized_pnl", str(ars.total_realized_pnl) if ars.total_realized_pnl is not None else ""])
        writer.writerow(["pnl_currency", ars.pnl_currency or ""])
        writer.writerow(["accounting_warnings", ars.warnings_count])
        writer.writerow(["accounting_errors", ars.errors_count])

        total_proceeds = Decimal("0")
        total_cost_basis = Decimal("0")
        total_fees = Decimal("0")
        realized_gains = Decimal("0")
        realized_losses = Decimal("0")
        net_realized_pnl = Decimal("0")

        for e in result.accounting_result.events:
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

        writer.writerow(["total_proceeds", str(total_proceeds)])
        writer.writerow(["total_cost_basis", str(total_cost_basis)])
        writer.writerow(["total_fees", str(total_fees)])
        writer.writerow(["realized_gains", str(realized_gains)])
        writer.writerow(["realized_losses", str(realized_losses)])
        writer.writerow(["net_realized_pnl", str(net_realized_pnl)])

    writer.writerow(["warnings", len(result.warnings) + (len(result.accounting_result.warnings) if result.accounting_result else 0)])
    writer.writerow(["errors", len(result.errors) + (len(result.accounting_result.errors) if result.accounting_result else 0)])
    writer.writerow(["unresolved_events", s.unknown_transactions])

    return output.getvalue()


def _build_audit_trail(result: ProcessingResult) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    headers = [
        "transaction_id",
        "source_operation",
        "classification",
        "review_required",
    ]
    writer.writerow(headers)

    for tx in result.transactions:
        meta = tx.metadata or {}
        source_op = meta.get("source_operation", "")
        review_required = "Yes" if tx.transaction_type == TransactionType.UNKNOWN else "No"

        writer.writerow([
            tx.transaction_id,
            source_op,
            tx.transaction_type.value if tx.transaction_type else "UNKNOWN",
            review_required,
        ])

    return output.getvalue()


def _build_detailed_pnl(result: ProcessingResult) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    headers = [
        "P&L ID",
        "Asset",
        "Total Realized P&L",
        "Currency",
        "Consumption IDs",
        "Lot IDs",
        "Event IDs",
        "From Date",
        "To Date",
    ]
    writer.writerow(headers)

    if not result.accounting_result:
        writer.writerow(["No P&L data available", "", "", "", "", "", "", "", ""])
        return output.getvalue()

    for pnl in result.accounting_result.realized_pnl:
        writer.writerow([
            pnl.pnl_id,
            pnl.asset,
            str(pnl.total_realized_pnl),
            pnl.currency,
            ";".join(pnl.consumption_ids),
            ";".join(pnl.lot_ids),
            ";".join(pnl.event_ids),
            pnl.from_timestamp.isoformat() if pnl.from_timestamp else "",
            pnl.to_timestamp.isoformat() if pnl.to_timestamp else "",
        ])

    return output.getvalue()


def _build_holdings(result: ProcessingResult) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    headers = [
        "Lot ID",
        "Asset",
        "Acquisition Date",
        "Original Quantity",
        "Remaining Quantity",
        "Unit Cost",
        "Remaining Cost Basis",
        "Source Transaction ID",
    ]
    writer.writerow(headers)

    if not result.accounting_result:
        writer.writerow(["No holdings data available", "", "", "", "", "", "", ""])
        return output.getvalue()

    for lot in result.accounting_result.lots:
        writer.writerow([
            lot.lot_id,
            lot.asset,
            lot.acquired_timestamp.isoformat() if lot.acquired_timestamp else "",
            str(lot.acquired_quantity),
            str(lot.remaining_quantity),
            str(lot.unit_cost) if lot.unit_cost is not None else "",
            str(lot.remaining_quantity * lot.unit_cost) if lot.unit_cost is not None else "",
            lot.source_transaction_id,
        ])

    return output.getvalue()


def _build_missing_cost_basis(result: ProcessingResult) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    headers = [
        "Transaction ID",
        "Date",
        "Asset",
        "Quantity",
        "Issue",
        "Details",
    ]
    writer.writerow(headers)

    if not result.accounting_result:
        writer.writerow(["No missing cost basis data", "", "", "", "", ""])
        return output.getvalue()

    for event in result.accounting_result.events:
        if event.event_type == AccountingEventType.ACQUISITION and event.cost_basis is None:
            writer.writerow([
                event.source_transaction_ids[0] if event.source_transaction_ids else "",
                event.timestamp.isoformat() if event.timestamp else "",
                event.asset,
                str(event.quantity),
                "MISSING_COST_BASIS",
                "Acquisition has no cost basis",
            ])
        elif event.event_type == AccountingEventType.DISPOSAL and event.proceeds is None:
            writer.writerow([
                event.source_transaction_ids[0] if event.source_transaction_ids else "",
                event.timestamp.isoformat() if event.timestamp else "",
                event.asset,
                str(event.quantity),
                "MISSING_PROCEEDS",
                "Disposal has no proceeds",
            ])

    return output.getvalue()


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    workers = int(os.getenv("WORKERS", "1"))
    reload = os.getenv("ENVIRONMENT", "production") == "development"

    uvicorn.run(
        "backend.main:app",
        host=host,
        port=port,
        workers=workers,
        reload=reload,
    )
