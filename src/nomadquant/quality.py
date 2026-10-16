"""Read-only quality facts for the dashboard. No orders and no invented ratios."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from nomadquant.broker.capabilities import broker_capability_profile
from nomadquant.config import Settings
from nomadquant.finance.execution import CONVENTION_ID, execution_price
from nomadquant.research.models import CostModel
from nomadquant.shadow.data_ops import data_check
from nomadquant.shadow.pilot import forward_pilot_report
from nomadquant.shadow.preflight import run_reconcile
from nomadquant.shadow.store import ShadowStore
from nomadquant.shadow.verify import verify_cycle

_BASE = CostModel(spread_bps=Decimal("1"), slippage_bps=Decimal("1"))
_OPTIMISTIC = CostModel(spread_bps=Decimal("0"), slippage_bps=Decimal("0"))
_STRESS = CostModel(spread_bps=Decimal("5"), slippage_bps=Decimal("10"))


def quality_report(settings: Settings) -> dict[str, Any]:
    mid = Decimal("100")
    reconcile = run_reconcile(settings)
    coverage = data_check(settings, feed="sip")
    pilot = forward_pilot_report(settings, verify_limit=2)
    cycles = _cycle_scopes(settings)
    return {
        "ci": {
            "result": "NOT_RECORDED_IN_PROCESS",
            "commit": None,
            "note": "GitHub Actions is outside this process. Do not invent a green check.",
        },
        "execution_convention": CONVENTION_ID,
        "cost_scenarios": {
            "note": "Diagnostic prices for a $100 mid. Not a forecast or a tuned strategy.",
            "optimistic_buy": str(execution_price(mid, _OPTIMISTIC, side="buy")),
            "base_buy": str(execution_price(mid, _BASE, side="buy")),
            "stress_buy": str(execution_price(mid, _STRESS, side="buy")),
        },
        "data_completeness": {
            "status": coverage.get("status"),
            "missing_count": coverage.get("missing_count"),
            "symbols": coverage.get("symbols"),
        },
        "revision_conflicts": "not_run",
        "accounting_reconciliation_ok": bool(reconcile.get("ok")),
        "pilot": {
            "status": pilot.get("status"),
            "prospective_decisions": pilot.get("prospective_decisions"),
            "hypothetical_fills": pilot.get("hypothetical_fills"),
            "sessions_missed": pilot.get("sessions_missed"),
            "sample": "insufficient" if not pilot.get("hypothetical_fills") else "observing",
            "readiness": (pilot.get("supervision") or {}).get("readiness"),
            "reasons": (pilot.get("supervision") or {}).get("reasons"),
        },
        "verifier": cycles,
        "broker": {
            "order_submission_implemented": False,
            "paper_balance_assumed_usd": None,
            "profile_version": broker_capability_profile()["profile_version"],
        },
        "unresolved": [
            "Raw prices are not total returns. Dividends and split files are absent.",
            "The forward sample has no hypothetical fill, so performance is inconclusive.",
            "A revision audit of stored bars was not run by this report.",
            "Alpaca paper equity was not read and is not the internal $100 book.",
            "A risk APPROVE is not a fill. Projected cash uses the shared fill kernel.",
        ],
    }


def _cycle_scopes(settings: Settings) -> dict[str, Any]:
    from pathlib import Path

    path = Path(settings.shadow_path)
    if not path.exists():
        return {"cycles": [], "note": "shadow ledger is absent"}
    store = ShadowStore(path, namespace="forward")
    rows = []
    for cycle in store.list_cycles(limit=5):
        report = verify_cycle(settings, int(cycle["id"]))
        rows.append(
            {
                "cycle_id": cycle["id"],
                "status": cycle.get("status"),
                "verified": report.get("verified"),
                "full_cycle": (report.get("scopes") or {}).get("full_cycle"),
                "fill": "verified_fill"
                if cycle.get("status") == "filled" and report.get("verified")
                else "no_fill",
            }
        )
    return {"cycles": rows, "note": "Scopes come from the independent verifier."}
