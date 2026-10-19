"""Read-only $100 simulation performance. Does not create a fill."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from nomadquant.config import Settings
from nomadquant.finance.accounting import max_drawdown
from nomadquant.shadow.store import ShadowStore
from nomadquant.shadow.valuation import MarkQuote, value_snapshot

_PAGE = 20


def simulation_performance(settings: Settings) -> dict[str, Any]:
    from nomadquant.overview import overview
    from nomadquant.research.store import ResearchStore

    view = overview(settings)
    store = ShadowStore.open_readonly(settings.shadow_path)
    if store is None:
        body = _empty_forward()
    else:
        body = _from_store(store, _marks(settings, store.snapshot()))
    body["comparisons"] = {
        "cash": "Holding the $100 in cash is the current forward book.",
        "spy_buy_hold": _historical(settings, ResearchStore).get("spy_buy_hold"),
        "registered_strategy_historical": _historical(settings, ResearchStore).get("strategy"),
        "policy_constrained_lab": (
            "The Simulation Lab replay applies policy 1.2.0 to the same monthly signal. "
            "It is a historical simulation, not this forward book."
        ),
    }
    body["lifecycle"] = view["trading"].get("lifecycle")
    body["broker_orders"] = False
    body["label"] = "forward_shadow"
    body["sample_kind"] = "forward_observation"
    return body


def performance_from_store(
    store: ShadowStore, marks: dict[str, MarkQuote] | None = None
) -> dict[str, Any]:
    """Same figures the forward page reads, for an isolated ledger in tests."""
    return _from_store(store, marks or {})


def _from_store(store: ShadowStore, marks: dict[str, MarkQuote]) -> dict[str, Any]:
    snapshot = store.snapshot()
    totals = store.history_totals()
    valuation = value_snapshot(snapshot, marks)
    filled = store.list_cycles(limit=_PAGE, status="filled")
    rejected = _verdict_page(store, "REJECT")
    no_fill = store.list_cycles(limit=_PAGE, status="no_trade")
    equity_rows = store.equity_history(limit=500)
    equities: list[Decimal | None] = [Decimal(str(row["equity_usd"])) for row in equity_rows]
    drawdown = max_drawdown(equities)
    fills = int(totals.get("filled_shadow_intents") or 0)
    holdings = {key: str(value) for key, value in snapshot["holdings"].items()}
    empty = fills == 0 and not holdings and snapshot["cash_usd"] == Decimal("100")
    return {
        "starting_virtual_capital_usd": "100",
        "cash_usd": str(snapshot["cash_usd"]),
        "reserved_cash_usd": str(snapshot["reserved_cash_usd"]),
        "holdings": holdings,
        "cost_basis": {key: str(value) for key, value in snapshot["cost_basis"].items()},
        "equity_usd": None if valuation.equity_usd is None else str(valuation.equity_usd),
        "valuation_status": valuation.status,
        "mark_timestamp": valuation.valuation_as_of,
        "mark_source": valuation.reason,
        "realized_pnl_usd": str(valuation.realized_pnl_usd),
        "unrealized_pnl_usd": (
            None if valuation.unrealized_pnl_usd is None else str(valuation.unrealized_pnl_usd)
        ),
        "costs_usd": str(snapshot["total_costs_usd"]),
        "costs_note": (
            "Spread and slippage are inside the fill price and are not charged again. "
            "None have been charged."
            if empty
            else (
                "Attributed costs are recorded on the ledger. "
                "Spread and slippage stay inside the fill price."
            )
        ),
        "dividends": {
            "status": "NOT_EVALUABLE",
            "detail": "No dated dividend file is stored. Price-only closes are not total return.",
        },
        "drawdown": None if drawdown is None else str(drawdown),
        "exposure": None if valuation.exposure_usd is None else str(valuation.exposure_usd),
        "trade_history": [_trade(row) for row in filled],
        "rejected_or_skipped": [_trade(row) for row in rejected],
        "no_fill_events": [_trade(row) for row in no_fill],
        "pending_intents": int(totals.get("pending_intents") or 0),
        "monthly_decisions": [],
        "verification": {
            "cycles_total": totals.get("cycles_total"),
            "filled": fills,
            "rejected_proposals": totals.get("rejected_proposals"),
        },
        "prospective_fills": fills,
        "sample_sufficient": False,
        "sample_note": (
            "The forward sample has no completed simulated fill. "
            "A zero result is not evidence the strategy works."
            if empty
            else f"The forward ledger has {fills} simulated fill(s). That sample is still small."
        ),
        "ledger_version": snapshot["version"],
    }


def _empty_forward() -> dict[str, Any]:
    return {
        "starting_virtual_capital_usd": "100",
        "cash_usd": "100",
        "reserved_cash_usd": "0",
        "holdings": {},
        "cost_basis": {},
        "equity_usd": "100",
        "valuation_status": "ok",
        "mark_timestamp": None,
        "mark_source": "No forward ledger file is stored yet.",
        "realized_pnl_usd": "0",
        "unrealized_pnl_usd": "0",
        "costs_usd": "0",
        "costs_note": "No simulated fill has been recorded.",
        "dividends": {"status": "NOT_EVALUABLE", "detail": "No dated dividend file is stored."},
        "drawdown": None,
        "exposure": "0",
        "trade_history": [],
        "rejected_or_skipped": [],
        "no_fill_events": [],
        "pending_intents": 0,
        "monthly_decisions": [],
        "verification": {"cycles_total": 0, "filled": 0, "rejected_proposals": 0},
        "prospective_fills": 0,
        "sample_sufficient": False,
        "sample_note": (
            "The forward sample has no completed simulated fill. "
            "A zero result is not evidence the strategy works."
        ),
        "ledger_version": 0,
    }


def _trade(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "signal_session": row.get("signal_session"),
        "fill_session": row.get("fill_session"),
        "status": row.get("status"),
        "side": row.get("fill_side"),
        "quantity": row.get("fill_qty"),
        "price": row.get("fill_price"),
        "costs_usd": row.get("costs_usd"),
        "risk_verdict": row.get("risk_verdict"),
    }


def _verdict_page(store: ShadowStore, verdict: str) -> list[dict[str, Any]]:
    rows = store.list_cycles(limit=100)
    matched = [row for row in rows if row.get("risk_verdict") == verdict]
    return matched[:_PAGE]


def _marks(settings: Settings, snapshot: dict[str, Any]) -> dict[str, MarkQuote]:
    holdings = snapshot.get("holdings") or {}
    if not holdings:
        return {}
    from datetime import UTC, datetime

    from nomadquant.marketdata.store import MarketStore

    market = MarketStore.open_readonly(settings.market_data_path)
    if market is None:
        return {}
    marks: dict[str, MarkQuote] = {}
    for symbol in holdings:
        sessions = sorted(market.sessions(str(symbol), "sip"))
        if not sessions:
            continue
        last = sessions[-1]
        rows = market.session_ohlc(str(symbol), "sip", last, last)
        if not rows:
            continue
        close = rows[-1][4]
        marks[str(symbol)] = MarkQuote(
            symbol=str(symbol),
            price=close,
            as_of=datetime(last.year, last.month, last.day, 21, tzinfo=UTC),
            feed="sip",
            source="stored_daily_close",
        )
    return marks


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
    label = "insufficient_data_v1"
    if not runs:
        runs = [
            item for item in store.list_runs("spy-tsmom-v1") if item.get("status") == "succeeded"
        ]
        label = "legacy_null_is_cash_v1"
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
