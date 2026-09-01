from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import os
import sys
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.ingestion.reader import read_csv_safely, MAX_FILE_SIZE_BYTES
from backend.ingestion.detector import detect_exchange
from backend.accounting.configuration import AccountingConfiguration
from backend.processing.pipeline import ProcessingPipeline
from backend.processing.models import ProcessingResult
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
