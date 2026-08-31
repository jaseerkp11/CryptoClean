from typing import Dict, List, Tuple

EXCHANGE_SIGNATURES = [
    {
        "id": "binance",
        "report_type": "spot_trade_history",
        "filename_keywords": ["binance"],
        "required_columns": [
            "date(utc)",
            "pair",
            "type",
            "order price",
            "amount",
        ],
        "optional_columns": [
            "average price",
            "filled",
            "total",
            "fee",
            "fee coin",
            "status",
        ],
        "sample_value_checks": {},
    },
    {
        "id": "binance",
        "report_type": "transaction_record",
        "filename_keywords": ["binance"],
        "required_columns": [
            "user id",
            "time",
            "account",
            "operation",
            "coin",
            "change",
            "remark",
        ],
        "optional_columns": [],
        "sample_value_checks": {},
    },
    {
        "id": "coinbase",
        "report_type": "transaction_record",
        "filename_keywords": ["coinbase"],
        "required_columns": [
            "timestamp",
            "transaction type",
            "asset",
            "quantity transacted",
        ],
        "optional_columns": [
            "spot price currency",
            "spot price at transaction",
            "subtotal",
            "total (inclusive of fees)",
            "fees",
            "notes",
        ],
        "sample_value_checks": {},
    },
    {
        "id": "bybit",
        "report_type": "transaction_record",
        "filename_keywords": ["bybit"],
        "required_columns": [
            "exec time",
            "symbol",
            "exec type",
            "order qty",
            "exec qty",
        ],
        "optional_columns": [
            "order price",
            "exec price",
            "fee",
            "order avg price",
            "type",
            "subject",
        ],
        "sample_value_checks": {},
    },
]


def _normalize(value: str) -> str:
    return value.strip().lower()


def _score_filename(filename: str, signature: Dict) -> float:
    lowered = filename.lower()
    for kw in signature["filename_keywords"]:
        if kw in lowered:
            return 0.10
    return 0.0


def _score_columns(
    column_names: List[str], signature: Dict
) -> Tuple[float, int, int]:
    normalized = [_normalize(c) for c in column_names]
    matched_required = 0
    for col in signature["required_columns"]:
        if any(col == c for c in normalized):
            matched_required += 1

    required_total = len(signature["required_columns"])
    required_ratio = matched_required / required_total if required_total > 0 else 1.0

    matched_optional = 0
    for col in signature["optional_columns"]:
        if any(col == c for c in normalized):
            matched_optional += 1

    optional_total = len(signature["optional_columns"])
    optional_ratio = matched_optional / optional_total if optional_total > 0 else 0.0

    if required_ratio < 0.5:
        return 0.0, matched_required, required_total

    score = (required_ratio * 0.80) + (optional_ratio * 0.10)
    return score, matched_required, required_total


def _is_ambiguous(
    candidates: List[Tuple[float, Dict, List[str], List[str]]],
    ambiguity_margin: float = 0.15,
    strong_threshold: float = 0.65,
) -> bool:
    if len(candidates) < 2:
        return False
    top_score = candidates[0][0]
    second_score = candidates[1][0]
    return (
        top_score >= strong_threshold
        and second_score >= strong_threshold
        and (top_score - second_score) < ambiguity_margin
    )


def detect_exchange(
    filename: str,
    df: "pd.DataFrame",
    column_names: List[str],
) -> Tuple[str, str, float, List[str], List[str]]:
    candidates: List[Tuple[float, Dict, List[str], List[str]]] = []

    for sig in EXCHANGE_SIGNATURES:
        score = 0.0
        indicators: List[str] = []

        filename_score = _score_filename(filename, sig)
        column_score, matched_required, required_total = _score_columns(
            column_names, sig
        )

        if column_score <= 0.0:
            continue

        score = column_score + filename_score
        if filename_score > 0:
            indicators.append(f"filename contains '{sig['filename_keywords'][0]}'")
        if column_score > 0:
            indicators.append(
                f"column pattern matched ({matched_required}/{required_total} required)"
            )

        candidates.append((score, sig, indicators, []))

    if not candidates:
        return "unknown", "transaction_record", 0.0, [], []

    candidates.sort(key=lambda x: x[0], reverse=True)

    if _is_ambiguous(candidates):
        top_sig = candidates[0][1]
        return (
            "unknown",
            "transaction_record",
            0.0,
            [],
            [
                "Multiple report signatures match with similar confidence; "
                f"cannot disambiguate between {top_sig['id']} report types."
            ],
        )

    best_score, best_sig, best_indicators, best_warnings = candidates[0]

    if best_score < 0.55:
        return "unknown", "transaction_record", 0.0, [], []

    return (
        best_sig["id"],
        best_sig.get("report_type", "transaction_record"),
        round(best_score, 2),
        best_indicators,
        best_warnings,
    )
