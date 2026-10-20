"""How agent evidence may change a deterministic candidate.

Agents may abstain or cut a buy. They cannot create a buy, enlarge a buy,
change the symbol, or override a risk rejection. Policy daily_agent_influence_1.0.0.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from nomadquant.daily.registry import INFLUENCE_POLICY, SPECS


def apply_influence(
    baseline: dict[str, str] | None,
    agent: dict[str, Any] | None,
) -> dict[str, Any]:
    base_action = "HOLD" if baseline is None else baseline["action"]
    symbol = None if baseline is None else baseline["symbol"]
    strategy_id = None if baseline is None else baseline["strategy_id"]
    notional = Decimal("0") if baseline is None else Decimal(baseline["notional_usd"])
    if agent is None or agent.get("valid") is not True:
        return _result(
            baseline_action=base_action,
            action="HOLD",
            symbol=symbol,
            strategy_id=strategy_id,
            notional=Decimal("0"),
            reason="agent_unavailable",
            disagreement=base_action != "HOLD",
            objections=[],
        )
    stance = str(agent.get("skeptic_stance") or "HOLD")
    uncertainty = bool(agent.get("material_uncertainty"))
    objections = [str(item) for item in agent.get("objections") or []]
    requested = str(agent.get("portfolio_action") or "HOLD")
    requested_symbol = agent.get("symbol")
    if requested_symbol not in {None, symbol}:
        requested = "HOLD"
        objections.append("rejected_symbol_change")
    if base_action == "HOLD" or requested == "HOLD" or stance == "HOLD":
        action = "HOLD"
        notional = Decimal("0")
        reason = "abstain"
    elif requested != base_action:
        action = "HOLD"
        notional = Decimal("0")
        reason = "agent_disagreed_with_baseline"
    else:
        action = base_action
        reason = "agent_agreed"
        if action == "BUY" and uncertainty:
            notional = (notional * Decimal("0.5")).quantize(Decimal("0.01"))
            reason = "uncertainty_reduced_size"
        if strategy_id in SPECS and notional > SPECS[strategy_id].notional_cap:
            notional = SPECS[strategy_id].notional_cap
    return _result(
        baseline_action=base_action,
        action=action,
        symbol=symbol,
        strategy_id=strategy_id,
        notional=notional,
        reason=reason,
        disagreement=action != base_action,
        objections=objections,
    )


def _result(
    *,
    baseline_action: str,
    action: str,
    symbol: str | None,
    strategy_id: str | None,
    notional: Decimal,
    reason: str,
    disagreement: bool,
    objections: list[str],
) -> dict[str, Any]:
    return {
        "policy": INFLUENCE_POLICY,
        "baseline_action": baseline_action,
        "baseline_label": "hypothetical_not_broker",
        "action": action,
        "symbol": symbol,
        "strategy_id": strategy_id,
        "notional_usd": format(notional, "f"),
        "reason": reason,
        "disagreement": disagreement,
        "objections": objections,
        "confidence_is_probability": False,
    }
