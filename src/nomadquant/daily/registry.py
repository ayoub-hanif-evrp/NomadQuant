"""Registered daily strategies. Parameters are fixed; they are not refit each session."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

UNIVERSE = frozenset({"SPY", "QQQ"})
INFLUENCE_POLICY = "daily_agent_influence_1.0.0"
RISK_POLICY = "daily_risk_1.0.0"
MAX_NEW_NOTIONAL = Decimal("25")
MAX_ORDERS_PER_SESSION = 1
STRATEGY_LOSS_STOP = Decimal("20")


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    version: str
    name: str
    holding_period: str
    research: str
    assumptions: str
    limitations: str
    do_not_trade: str
    parameter_selection: str
    notional_cap: Decimal


TREND = StrategySpec(
    strategy_id="etf_trend_sma_v1",
    version="1.0.0",
    name="Daily SMA trend filter",
    holding_period="Days to months, while price remains above the 200-session average.",
    research=(
        "Faber, M. (2007). A Quantitative Approach to Tactical Asset Allocation. "
        "Journal of Wealth Management. The published rule is a slow moving-average "
        "filter that holds the asset or cash. Brock, Lakonishok, and LeBaron (1992) "
        "document moving-average rules on index prices. This implementation uses a "
        "200-session simple average on daily closes, plus a realized-volatility cap."
    ),
    assumptions=(
        "A slow positive trend in a liquid ETF can persist long enough that standing "
        "aside below the average avoids part of a decline. Cash is a valid position. "
        "The signal uses only closes available after the session cutoff."
    ),
    limitations=(
        "The original Faber result is monthly and is not a guarantee for a daily "
        "200-session filter. Whipsaws around the average are expected. A volatility "
        "cap can keep the strategy in cash during a rebound. Historical tests are research."
    ),
    do_not_trade=(
        "Do not buy when the close is at or below the average, when 20-session "
        "daily volatility exceeds 2 percent, when fewer than 200 closes exist, or "
        "when the execution session has already passed."
    ),
    parameter_selection=(
        "200 sessions and a 2 percent daily-volatility cap are predeclared. They were "
        "not chosen by searching for the best historical profit on this repository's data."
    ),
    notional_cap=Decimal("25"),
)

REVERSAL = StrategySpec(
    strategy_id="etf_reversal_5d_v1",
    version="1.0.0",
    name="Five-session reversal inside an uptrend",
    holding_period="About one to five sessions after a stretched decline.",
    research=(
        "Jegadeesh (1990) and Lehmann (1990) document short-horizon reversal in "
        "individual equities. Index ETFs diversify idiosyncratic reversal, so the "
        "effect is weaker. This rule therefore requires both a large five-session "
        "decline and a close that is still above the 200-session average."
    ),
    assumptions=(
        "A sharp five-session drop that has not broken the slow uptrend can partially "
        "retrace. The rule is a hypothesis, not evidence that the next day will rise."
    ),
    limitations=(
        "Published reversal evidence is stronger for stocks than for SPY and QQQ. "
        "The trend filter removes crash-buying but also removes many observations. "
        "A few paper trades cannot confirm the hypothesis."
    ),
    do_not_trade=(
        "Do not buy below the 200-session average, when the five-session move is not "
        "at least 1.5 of its own trailing dispersion, when daily volatility exceeds "
        "2.5 percent, or when the trend strategy already requests a buy the same day."
    ),
    parameter_selection=(
        "Five sessions, a 1.5 dispersion threshold, and the 200-session regime filter "
        "are predeclared. They were not optimized against a profit target."
    ),
    notional_cap=Decimal("15"),
)

SPECS: dict[str, StrategySpec] = {
    TREND.strategy_id: TREND,
    REVERSAL.strategy_id: REVERSAL,
}


def public_registry() -> list[dict[str, str]]:
    return [
        {
            "strategy_id": spec.strategy_id,
            "version": spec.version,
            "name": spec.name,
            "holding_period": spec.holding_period,
            "research": spec.research,
            "do_not_trade": spec.do_not_trade,
            "notional_cap": format(spec.notional_cap, "f"),
        }
        for spec in SPECS.values()
    ]
