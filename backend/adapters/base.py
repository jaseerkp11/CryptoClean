from abc import ABC, abstractmethod
from typing import Any, Dict, List

from pydantic import BaseModel

from backend.models.transaction import CanonicalTransaction


class AdapterResult(BaseModel):
    transactions: List[CanonicalTransaction]
    warnings: List[str]
    errors: List[str]


class BaseAdapter(ABC):
    @abstractmethod
    def adapt(self, rows: List[Dict[str, Any]]) -> AdapterResult:
        ...
