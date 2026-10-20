"""Daily evaluation. It records a decision and does not submit while unauthorized."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from nomadquant.config import Settings
from nomadquant.daily.agents import LanguageModel, run_agents
from nomadquant.daily.authorization import authorization_status
from nomadquant.daily.engine import primary_candidate
from nomadquant.daily.mailer import deliver_notice
from nomadquant.daily.mcp_client import invoke_readonly_tools
from nomadquant.daily.mcp_server import MarketContext
from nomadquant.daily.registry import INFLUENCE_POLICY, RISK_POLICY, public_registry
from nomadquant.daily.store import (
    enqueue_notice,
    latest_decision,
    list_tool_calls,
    notice_status,
    save_decision,
    save_tool_call,
)
from nomadquant.marketdata.availability import modeled_available_at
from nomadquant.marketdata.calendar import is_session, next_session

Prices = dict[str, dict[Any, Decimal]]


def evaluate_daily(
    settings: Settings,
    *,
    prices: Prices,
    signal_session: Any,
    now: datetime,
    quotes: dict[str, dict[str, Any]] | None = None,
    headlines: list[dict[str, Any]] | None = None,
    sleeve: dict[str, str] | None = None,
    model: LanguageModel | None = None,
    use_mcp: bool = True,
) -> dict[str, Any]:
    """Record the baseline, the AI decision, and a queued notice. No broker call."""
    if not is_session(signal_session):
        execution = None
        reason = "market_holiday"
    else:
        execution = next_session(signal_session)
        reason = None
        if now < modeled_available_at(signal_session):
            reason = "signal_not_available"
    baseline = None if reason else primary_candidate(prices, signal_session)
    tool_rows: list[dict[str, Any]] = []
    if use_mcp and reason is None:
        context = MarketContext(
            now=now,
            prices=prices,
            quotes=quotes or {},
            headlines=headlines or [],
            sleeve=sleeve
            or {"remaining_usd": "100", "connectivity_excluded_from_strategy_pnl": "true"},
        )
        tool_rows = invoke_readonly_tools(context, now.isoformat())
        for row in tool_rows:
            save_tool_call(
                settings.daily_path,
                created_at=now.isoformat(),
                tool_name=str(row["tool"]),
                status="error" if row["is_error"] else "ok",
                payload=row,
            )
    decision = run_agents(baseline=baseline, tool_results=tool_rows, model=model)
    if reason == "market_holiday":
        decision = {**decision, "action": "HOLD", "reason": "market_holiday"}
    if reason == "signal_not_available":
        decision = {**decision, "action": "HOLD", "reason": "signal_not_available"}
    missed = (
        execution is not None and now.astimezone(ZoneInfo("America/New_York")).date() > execution
    )
    payload = {
        **decision,
        "signal_session": signal_session.isoformat(),
        "execution_session": None if execution is None else execution.isoformat(),
        "missed_window": missed,
        "submitted": False,
        "influence_policy": INFLUENCE_POLICY,
        "risk_policy": RISK_POLICY,
        "historical_replay_counts_as_performance": False,
        "schedule_installed": False,
    }
    save_decision(
        settings.daily_path,
        created_at=now.isoformat(),
        signal_session=signal_session.isoformat(),
        payload=payload,
    )
    notice = enqueue_notice(
        settings.daily_path,
        created_at=now.isoformat(),
        subject=f"Daily decision {payload['action']}",
        body=(
            f"Action {payload['action']}. Strategy {payload.get('strategy_id')}. "
            f"Baseline {payload.get('baseline_action')} is hypothetical and was not sent "
            "to Alpaca. Connectivity-test P&L is excluded."
        ),
    )
    delivery = deliver_notice(settings, int(notice["id"]))
    payload["email"] = delivery
    return payload


def daily_status(settings: Settings, *, now: datetime | None = None) -> dict[str, Any]:
    clock = now or datetime.now(UTC)
    auth = authorization_status(settings, now=clock)
    return {
        "label": "DAILY AI PAPER PILOT",
        "broker_orders_submitted_by_this_request": False,
        "live_trading": False,
        "authorization": auth,
        "strategies": public_registry(),
        "latest_decision": latest_decision(settings.daily_path),
        "tool_calls": list_tool_calls(settings.daily_path),
        "email": notice_status(settings.daily_path),
        "schedule_installed": False,
        "computer_must_be_on": True,
        "connectivity_position_isolated": True,
        "per_trade_approval": False,
        "emergency_stop": auth.get("reason") == "killed" or auth.get("enabled") is False,
        "activation_phrase": "AUTHORIZE_DAILY_PAPER_PILOT",
        "as_of": clock.isoformat(),
    }


def install_schedule(*, confirm: str) -> dict[str, bool | str]:
    """The task is never installed from this function."""
    del confirm
    return {"installed": False, "reason": "schedule_install_disabled"}
