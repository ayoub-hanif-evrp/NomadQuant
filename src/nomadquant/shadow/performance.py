"""Read-only $100 simulation performance. Does not create a fill."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nomadquant.config import Settings


def simulation_performance(settings: Settings) -> dict[str, Any]:
    from nomadquant.overview import overview
    from nomadquant.research.store import ResearchStore

    view = overview(settings)
    portfolio = view["portfolio"]
    trading = view["trading"]
    fills = int(portfolio.get("simulated_fills") or 0)
    historical = _historical(settings, ResearchStore)
    return {
        "starting_virtual_capital_usd": "100",
        "cash_usd": portfolio.get("cash_usd"),
        "reserved_cash_usd": "0" if fills == 0 else None,
        "holdings": portfolio.get("holdings") or {},
        "equity_usd": portfolio.get("equity_usd"),
        "mark_timestamp": view["data"].get("latest_stored"),
        "realized_pnl_usd": "0" if fills == 0 else None,
        "unrealized_pnl_usd": "0" if fills == 0 else None,
        "costs_note": "Spread and slippage are inside a fill price. None have been charged.",
        "dividends": {
            "status": "NOT_EVALUABLE",
            "detail": "No dated dividend file is stored. Price-only closes are not total return.",
        },
        "drawdown": None,
        "exposure": "0" if not portfolio.get("holdings") else None,
        "trade_history": [],
        "rejected_or_skipped": [],
        "no_fill_events": [],
        "monthly_decisions": trading.get("recent_decisions") or [],
        "expected_vs_observed": "No observed-quote fill has been recorded.",
        "prospective_fills": fills,
        "sample_sufficient": False,
        "sample_note": (
            "The forward sample has no completed simulated fill. "
            "A zero result is not evidence the strategy works."
        ),
        "comparisons": {
            "cash": "Holding the $100 in cash is the current forward book.",
            "spy_buy_hold": historical.get("spy_buy_hold"),
            "registered_strategy_historical": historical.get("strategy"),
        },
        "cost_sensitivity": {
            "note": "1 bp and 10 bp prices are research stress cases, not a forward fit.",
            "one_bp_buy_at_100": "100.015",
            "ten_bp_buy_at_100": "100.15",
        },
        "lifecycle": trading.get("lifecycle"),
        "broker_orders": False,
        "label": "internal_100_simulation",
    }


def _historical(settings: Settings, store_type: type) -> dict[str, Any]:
    path = Path(settings.research_path)
    if not path.exists():
        return {"strategy": None, "spy_buy_hold": None}
    store = store_type(path)
    runs = [
        item
        for item in store.list_runs("spy-tsmom-v1-insufficient-data")
        if item.get("status") == "succeeded"
    ]
    if not runs:
        runs = [
            item for item in store.list_runs("spy-tsmom-v1") if item.get("status") == "succeeded"
        ]
        label = "legacy_null_is_cash_v1"
    else:
        label = "insufficient_data_v1"
    if not runs:
        return {"strategy": None, "spy_buy_hold": None}
    latest = runs[0]
    rows = store.metrics(int(latest["id"]))
    strategy = next(
        (
            row
            for row in rows
            if row.get("strategy_id") == "spy_tsmom_12_1" and row.get("window") == "test"
        ),
        None,
    )
    buy_hold = next(
        (
            row
            for row in rows
            if row.get("strategy_id") == "spy_buy_hold" and row.get("window") == "test"
        ),
        None,
    )
    return {
        "strategy": {
            "run_id": latest["id"],
            "convention": label,
            "window": "test",
            "net_return": None if strategy is None else strategy.get("net_return"),
            "label": "historical_price_only_not_a_forward_fill",
            "dividends": "NOT_EVALUABLE",
        },
        "spy_buy_hold": None
        if buy_hold is None
        else {
            "run_id": latest["id"],
            "window": "test",
            "net_return": buy_hold.get("net_return"),
            "label": "historical_price_only_buy_hold",
        },
    }
