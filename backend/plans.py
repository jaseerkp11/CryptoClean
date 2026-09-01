from __future__ import annotations

from typing import Dict, Optional


class Plan:
    FREE = "free"
    STANDARD = "standard"
    COMPLETE = "complete"


PLAN_CONFIG: Dict[str, Dict] = {
    Plan.FREE: {
        "name": "Free Report",
        "price": "$0",
        "limit": 100,
        "accounting": False,
        "label": "FREE",
    },
    Plan.STANDARD: {
        "name": "Standard Report",
        "price": "$9",
        "limit": 5000,
        "accounting": True,
        "label": "STANDARD",
    },
    Plan.COMPLETE: {
        "name": "Complete Report",
        "price": "$19",
        "limit": None,
        "accounting": True,
        "label": "COMPLETE",
    },
}


def get_plan_config(plan: str) -> Dict:
    if plan not in PLAN_CONFIG:
        raise ValueError(f"Unknown plan: {plan}")
    return PLAN_CONFIG[plan]


def resolve_plan_from_frontend(plan: Optional[str]) -> str:
    if not plan or plan not in PLAN_CONFIG:
        return Plan.FREE
    return plan
