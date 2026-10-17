"""One bounded daily workflow. Scheduling stays off unless the user enables it later.

Inspect and dry-run never require a new approval email. Shadow-apply is refused
here unless the caller passes an explicit test authorization. Agents cannot call this.
"""

from __future__ import annotations

from typing import Any

from nomadquant.config import Settings

STEPS = (
    "check_nyse_calendar",
    "update_historical_data_only_if_requested",
    "check_completeness",
    "monitor_pending_signals",
    "calculate_scheduled_decision",
    "deterministic_risk_and_sizing",
    "proposal_buy_sell_or_hold",
    "email_only_for_a_real_buy_or_sell",
    "wait_for_explicit_approval",
    "revalidate_before_mutation",
    "simulate_fill_or_no_fill",
    "reconcile_ledger",
    "record_result",
)


def workflow_plan() -> dict[str, Any]:
    return {
        "steps": list(STEPS),
        "schedule_installed": False,
        "agents_can_approve": False,
        "broker_orders": False,
        "after_hours_fill": "refused",
        "approval_email": "only after a real BUY or SELL proposal",
        "default_mode": "inspect",
    }


def run_supervised(
    settings: Settings,
    *,
    mode: str = "inspect",
    sync: bool = False,
    allow_apply: bool = False,
) -> dict[str, Any]:
    if mode not in {"inspect", "dry-run", "shadow-apply"}:
        raise ValueError("mode must be inspect, dry-run, or shadow-apply")
    if mode == "shadow-apply" and not allow_apply:
        return {
            "status": "REFUSED",
            "reason": "forward_apply_requires_explicit_authorization",
            "plan": workflow_plan(),
            "broker_orders": False,
        }
    from nomadquant.shadow.daily import run_daily_operation

    code, payload = run_daily_operation(settings, mode=mode, sync=sync, feed="sip")
    cycle = (payload.get("worker") or {}).get("cycle") or {}
    intent = str(cycle.get("intent") or "")
    emailed = False
    awaiting = cycle.get("status") == "awaiting_approval" and intent in {"buy", "sell"}
    if mode == "shadow-apply" and awaiting:
        from nomadquant.approvals.service import issue_proposal_from_cycle

        issue_proposal_from_cycle(settings, cycle)
        emailed = True
    return {
        "status": "COMPLETED" if code == 0 else "FAILED",
        "exit_code": code,
        "mode": mode,
        "intent": intent or None,
        "approval_email_sent": emailed,
        "broker_orders": False,
        "daily": payload,
    }
