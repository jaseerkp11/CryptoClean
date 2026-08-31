from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict

from backend.accounting.models import ExceptionCode, WarningCode, AccountingWarning, AccountingException


__all__ = ["AccountingWarning", "AccountingException", "make_warning", "make_exception"]


def make_warning(
    code: WarningCode,
    message: str,
    source_transaction_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> AccountingWarning:
    import hashlib

    raw = "|".join(sorted([code.value, message or "", source_transaction_id or "", str(context or "")]))
    warning_id = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return AccountingWarning(
        warning_id=warning_id,
        code=code,
        message=message,
        source_transaction_id=source_transaction_id,
        context=context,
    )


def make_exception(
    code: ExceptionCode,
    message: str,
    source_transaction_id: Optional[str] = None,
) -> AccountingException:
    import hashlib

    raw = "|".join(sorted([code.value, message or "", source_transaction_id or ""]))
    exception_id = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return AccountingException(
        exception_id=exception_id,
        code=code,
        message=message,
        source_transaction_id=source_transaction_id,
    )
