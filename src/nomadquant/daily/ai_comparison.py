"""Compare the deterministic rule with the AI filter. A missing model is not a result."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from nomadquant.daily.engine import primary_candidate
from nomadquant.daily.influence import apply_influence


def compare_ai_filter(
    prices: dict[str, dict[date, Decimal]],
    sessions: list[date],
    *,
    model_available: bool,
) -> dict[str, Any]:
    """Score both paths on the same closes.

    When the model is unavailable the agent path fail-closes to HOLD. Those
    HOLDs are not counted as useful vetoes, because no model examined the evidence.
    """
    deterministic_buys = 0
    compared = 0
    for day in sessions:
        if day not in (prices.get("SPY") or {}):
            continue
        choice = primary_candidate(prices, day, {})
        if choice is None:
            continue
        compared += 1
        if choice["action"] == "BUY":
            deterministic_buys += 1
        if model_available:
            continue
        blocked = apply_influence(choice, None)
        if blocked["action"] != "HOLD":
            raise RuntimeError("A missing agent must not create or keep a buy.")
    if not model_available:
        return {
            "label": "historical_research",
            "recommendation": "DETERMINISTIC_BASELINE",
            "ai_incremental_benefit": None,
            "reason": "model_not_measured",
            "deterministic_buy_signals": deterministic_buys,
            "sessions_compared": compared,
            "vetoes_counted": 0,
            "measurement": "NOT_MEASURED",
            "permission_to_trade": False,
            "live_ollama_session": False,
        }
    return {
        "label": "historical_research",
        "recommendation": "NOT_COMPARED",
        "ai_incremental_benefit": None,
        "reason": "live_model_output_not_supplied",
        "deterministic_buy_signals": deterministic_buys,
        "sessions_compared": compared,
        "vetoes_counted": 0,
        "measurement": "NOT_MEASURED",
        "permission_to_trade": False,
        "live_ollama_session": False,
    }
