"""Deterministic checks of numeric claims against stored research metrics.

A PASS means the number matches the stored backtest within tolerance. It says
nothing about statistical significance or future performance.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from nomadquant.agents.schemas import Claim
from nomadquant.research.store import ResearchStore

TOLERANCE = Decimal("0.000001")
CLAIM_NAMES = ("net_return", "sharpe", "max_drawdown", "trade_count", "total_costs")
CLAIM_ALIASES = {"sharpe_ratio": "sharpe", "sharpe_ratio_annual": "sharpe"}
DEFAULT_WINDOW = "test"

_FRACTION_UNITS = {"", "fraction", "ratio"}
_PERCENT_UNITS = {"percent", "pct", "%"}
_ALLOWED_UNITS: dict[str, set[str]] = {
    "net_return": _FRACTION_UNITS | _PERCENT_UNITS,
    "max_drawdown": _FRACTION_UNITS | _PERCENT_UNITS,
    "sharpe": {"", "ratio"},
    "trade_count": {"", "count", "trades"},
    "total_costs": {"", "usd", "$"},
}
_REF_PATTERN = re.compile(r"^(?:research_run|run|metrics)[:#/ ]*(\d+)(?:\D.*)?$", re.IGNORECASE)
_STRATEGY_REF = re.compile(
    r"^(?:research_run|run|metrics|strategy)[:#/ ]+([A-Za-z][\w.-]*)$",
    re.IGNORECASE,
)


def offline_claim_benchmark() -> dict[str, Any]:
    """Fixed claims against one metric row. No model and no network."""
    metrics = [
        {
            "strategy_id": "spy_tsmom_12_1",
            "window": "test",
            "net_return": "0.0123",
            "sharpe": "0.80",
            "max_drawdown": "0.05",
            "trade_count": "12",
            "total_costs": "1.25",
        }
    ]
    cases = [
        (
            "percent matches decimal",
            {
                "name": "net_return",
                "value": "1.23",
                "unit": "percent",
                "evidence_ref": "run:7",
                "window": "test",
            },
            "PASS",
        ),
        (
            "decimal return",
            {
                "name": "net_return",
                "value": "0.0123",
                "unit": "fraction",
                "evidence_ref": "run:7",
                "window": "test",
            },
            "PASS",
        ),
        (
            "wrong percent",
            {
                "name": "net_return",
                "value": "12.3",
                "unit": "percent",
                "evidence_ref": "run:7",
                "window": "test",
            },
            "FAIL",
        ),
        (
            "missing reference",
            {
                "name": "sharpe",
                "value": "0.80",
                "unit": "ratio",
                "evidence_ref": " ",
                "window": "test",
            },
            "FAIL",
        ),
        (
            "unknown name",
            {"name": "alpha", "value": "1", "unit": "", "evidence_ref": "run:7", "window": "test"},
            "FAIL",
        ),
    ]
    rows = []
    for label, raw, expected in cases:
        claim = Claim.model_validate(raw)
        result = _check(claim, claim.model_dump(mode="json"), 7, "spy_tsmom_12_1", metrics)
        rows.append({"label": label, "expected": expected, "verdict": result["verdict"]})
    matched = sum(1 for row in rows if row["verdict"] == row["expected"])
    return {
        "cases": rows,
        "matched": matched,
        "total": len(rows),
        "pass": matched == len(rows),
        "models_called": False,
        "note": "This scores the checker, not a language model's forecasting skill.",
    }


def verify_claims(
    claims: Sequence[Claim | dict[str, Any]],
    research_path: str | Path,
    run_id: int,
) -> list[dict[str, Any]]:
    """Return one {claim, verdict, detail} entry per claim, in order."""
    store = ResearchStore(research_path)
    run = store.get_run(run_id)
    metrics = store.metrics(run_id) if run is not None else []
    strategy_id = str(run["config"].get("strategy_id", "")) if run is not None else ""
    results: list[dict[str, Any]] = []
    for raw in claims:
        try:
            claim = raw if isinstance(raw, Claim) else Claim.model_validate(raw)
        except ValidationError:
            shown = raw if isinstance(raw, dict) else raw.model_dump(mode="json")
            results.append(_result(shown, "FAIL", "Claim is malformed and was rejected."))
            continue
        shown = claim.model_dump(mode="json")
        if run is None:
            results.append(_result(shown, "NOT_EVALUABLE", "Research run was not found."))
            continue
        results.append(_check(claim, shown, run_id, strategy_id, metrics))
    return results


def _check(
    claim: Claim,
    shown: dict[str, Any],
    run_id: int,
    strategy_id: str,
    metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    if not claim.evidence_ref.strip():
        return _result(shown, "FAIL", "A numerical claim requires an evidence reference.")
    name = CLAIM_ALIASES.get(claim.name.strip(), claim.name.strip())
    if name not in CLAIM_NAMES:
        return _result(shown, "FAIL", f"Unknown claim name {claim.name!r} was rejected.")
    ref_error = _resolve_run_ref(claim.evidence_ref, run_id, strategy_id)
    if ref_error is not None:
        return _result(shown, ref_error[0], ref_error[1])
    unit = claim.unit.strip().lower()
    if unit not in _ALLOWED_UNITS[name]:
        return _result(shown, "FAIL", f"Unit {claim.unit!r} is not valid for {name}.")
    window = (claim.window or DEFAULT_WINDOW).strip()
    row = next(
        (
            item
            for item in metrics
            if item["strategy_id"] == strategy_id and item["window"] == window
        ),
        None,
    )
    if row is None:
        return _result(shown, "NOT_EVALUABLE", f"No stored metrics for window {window!r}.")
    stored_raw = row.get(name)
    if stored_raw is None:
        return _result(shown, "NOT_EVALUABLE", f"{name} is undefined for window {window!r}.")
    try:
        stored = Decimal(str(stored_raw))
    except InvalidOperation:
        return _result(shown, "NOT_EVALUABLE", f"Stored {name} is not numeric.")
    claimed = claim.value
    if unit in _PERCENT_UNITS:
        claimed = claimed / Decimal(100)
    if not claimed.is_finite():
        return _result(shown, "FAIL", "Claimed value is not finite.")
    if abs(claimed - stored) <= TOLERANCE:
        return _result(shown, "PASS", f"{name}={stored} in window {window!r} matches.")
    return _result(
        shown, "FAIL", f"{name} claimed {claimed} but stored {stored} in window {window!r}."
    )


def _resolve_run_ref(evidence_ref: str, run_id: int, strategy_id: str) -> tuple[str, str] | None:
    """Return (verdict, detail) on failure, else None when the ref targets this run."""
    text = evidence_ref.strip()
    match = _REF_PATTERN.match(text)
    if match is not None:
        if int(match.group(1)) != run_id:
            return (
                "FAIL",
                f"Evidence reference points at run {match.group(1)}, not run {run_id}.",
            )
        return None
    strat = _STRATEGY_REF.match(text)
    if strat is not None and strategy_id and strat.group(1) == strategy_id:
        return None
    if strategy_id and text in {strategy_id, f"run:{strategy_id}", f"strategy:{strategy_id}"}:
        return None
    return ("NOT_EVALUABLE", "Evidence reference does not identify a research run.")


def _result(claim: dict[str, Any], verdict: str, detail: str) -> dict[str, Any]:
    return {"claim": claim, "verdict": verdict, "detail": detail}
