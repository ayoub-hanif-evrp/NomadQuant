"""Read-only shadow portfolio and cycle APIs. No order submission."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from nomadquant.shadow.marks import value_forward_portfolio
from nomadquant.shadow.preflight import run_preflight, run_reconcile
from nomadquant.shadow.store import MigrationRequired, ShadowStore
from nomadquant.shadow.valuation import PortfolioValuation
from nomadquant.shadow.worker import (
    list_worker_runs,
    outbox_backlog_count,
    read_last_worker_run,
    recovery_required,
)

router = APIRouter(prefix="/api/shadow")


def _store(request: Request) -> ShadowStore | None:
    path = Path(request.app.state.settings.shadow_path)
    if not path.is_file():
        return None
    try:
        return ShadowStore.open_readonly(path)
    except MigrationRequired as exc:
        raise HTTPException(status_code=409, detail="MIGRATION_REQUIRED") from exc


def _valuation(request: Request, store: ShadowStore) -> PortfolioValuation:
    settings = request.app.state.settings
    return value_forward_portfolio(store.snapshot(), settings.market_data_path)


@router.get("/status")
def shadow_status(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    store = _store(request)
    if store is None:
        return {
            "trading_state": "SHADOW_ONLY",
            "allow_order_submission": False,
            "starting_capital_usd": "100",
            "initialized": False,
            "cycle_count": 0,
            "valuation": None,
            "note": "Shadow ledger not created yet. Run nomadquant-shadow cycle.",
        }
    snap = store.snapshot()
    valuation = _valuation(request, store)
    return {
        "trading_state": "SHADOW_ONLY",
        "allow_order_submission": settings.allow_order_submission,
        "initialized": True,
        "starting_capital_usd": str(snap["starting_capital_usd"]),
        "cash_usd": str(snap["cash_usd"]),
        "reserved_cash_usd": str(snap["reserved_cash_usd"]),
        "holdings": {k: str(v) for k, v in snap["holdings"].items()},
        "cost_basis": {k: str(v) for k, v in snap["cost_basis"].items()},
        "realized_pnl_usd": str(snap["realized_pnl_usd"]),
        "total_costs_usd": str(snap["total_costs_usd"]),
        "peak_equity_usd": str(snap["peak_equity_usd"]),
        "ledger_version": snap["version"],
        "updated_at": snap["updated_at"],
        "cycle_count": store.count_cycles(),
        "valuation": valuation.as_dict(),
        "note": (
            "Internal $100 shadow ledger only. Equity from backend valuation "
            "(cash + qty × mark). Not Alpaca paper profits; no broker orders."
        ),
    }


@router.get("/valuation")
def shadow_valuation(request: Request) -> dict[str, Any]:
    store = _store(request)
    if store is None:
        return {
            "status": "valuation_unavailable",
            "cash_usd": "100",
            "reserved_cash_usd": "0",
            "available_cash_usd": "100",
            "positions": [],
            "equity_usd": None,
            "exposure_usd": None,
            "exposure_fraction": None,
            "realized_pnl_usd": "0",
            "unrealized_pnl_usd": None,
            "total_costs_usd": "0",
            "starting_capital_usd": "100",
            "valuation_as_of": None,
            "reason": "Shadow ledger not initialized.",
            "ledger_version": 0,
        }
    return _valuation(request, store).as_dict()


@router.get("/ops")
def shadow_ops(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    store = _store(request)
    alerts: list[dict[str, Any]] = []
    market_path = Path(settings.market_data_path)
    market_info: dict[str, Any] = {
        "database_present": market_path.exists(),
        "feed": "sip",
        "symbols": ["SPY", "QQQ"],
        "feeds": ["sip"],
        "earliest_session": None,
        "latest_session": None,
        "bar_count": 0,
        "coverage_complete": False,
        "suitable_for_research": False,
        "last_successful_ingestion": None,
        "requested_start": None,
        "requested_end": None,
        "warnings": [],
        "coverage": [],
        "caveat": "Feed never auto-mixed. SIP entitlement required for SIP history.",
    }
    if market_path.exists():
        try:
            from nomadquant.marketdata.report import market_data_status
            from nomadquant.marketdata.store import MarketStore
            from nomadquant.shadow.cycle import LOOKBACK, SKIP

            market = MarketStore.open_readonly(market_path)
            if market is None:
                raise FileNotFoundError(market_path)
            sessions = (
                sorted(market.sessions("SPY", "sip")) if market.has_symbol("SPY", "sip") else []
            )
            market_info.update(
                {
                    "earliest_session": None if not sessions else sessions[0].isoformat(),
                    "latest_session": None if not sessions else sessions[-1].isoformat(),
                    "bar_count": len(sessions),
                }
            )
            if len(sessions) >= LOOKBACK + SKIP + 5:
                warm_start = sessions[-(LOOKBACK + SKIP + 5)]
                md = market_data_status(
                    str(market_path),
                    start=warm_start,
                    end=sessions[-1],
                    symbols=["SPY"],
                    feed="sip",
                )
                market_info.update(
                    {
                        "coverage_complete": md.coverage_complete,
                        "suitable_for_research": md.suitable_for_research,
                        "requested_start": md.requested_start,
                        "requested_end": md.requested_end,
                        "warnings": list(md.warnings),
                        "coverage": [c.model_dump() for c in md.coverage],
                        "last_successful_ingestion": md.last_successful_ingestion,
                        "readiness": "OK" if md.suitable_for_research else "INCOMPLETE",
                    }
                )
                if not md.suitable_for_research:
                    alerts.append(
                        {
                            "level": "warning",
                            "source": "market",
                            "message": "Coverage INCOMPLETE vs strategy warm-up calendar.",
                        }
                    )
            else:
                market_info["coverage_complete"] = False
                market_info["suitable_for_research"] = False
                market_info["readiness"] = "INCOMPLETE"
                market_info["warnings"].append("Insufficient sessions for strategy warm-up.")
                alerts.append(
                    {
                        "level": "warning",
                        "source": "market",
                        "message": "SPY/SIP warm-up window incomplete.",
                    }
                )
        except Exception as exc:  # noqa: BLE001
            market_info["warnings"].append(f"Market inspect failed: {exc}")
            market_info["readiness"] = "INCOMPLETE"
            alerts.append(
                {"level": "error", "source": "market", "message": "Market database unreadable."}
            )
    else:
        alerts.append(
            {"level": "warning", "source": "market", "message": "market.sqlite not present."}
        )

    pending: list[dict[str, Any]] = []
    last_cycle = None
    cycle_count = 0
    recovery_flag = False
    outbox_backlog: int | None = None
    if store is not None:
        recovery_flag = recovery_required(store)
        pending = store.pending_intents()
        outbox_backlog = outbox_backlog_count(store)
        cycles = store.list_cycles(limit=1)
        last_cycle = cycles[0] if cycles else None
        cycle_count = store.count_cycles()
        for res in store.list_active_reservations():
            alerts.append(
                {
                    "level": "error",
                    "source": "reservation",
                    "message": f"Stuck reservation {res['intent_id']}",
                }
            )
        if last_cycle and last_cycle.get("status") == "error":
            alerts.append(
                {
                    "level": "error",
                    "source": "cycle",
                    "message": "Last cycle failed.",
                    "cycle_id": last_cycle.get("id"),
                }
            )
        val = _valuation(request, store)
        if val.status != "ok":
            alerts.append(
                {
                    "level": "warning",
                    "source": "valuation",
                    "message": val.reason,
                }
            )

    if settings.allow_order_submission:
        alerts.append(
            {
                "level": "error",
                "source": "safety",
                "message": "ALLOW_ORDER_SUBMISSION must remain false.",
            }
        )

    log_dir = Path(settings.shadow_path).parent / "shadow_logs"
    last_worker = read_last_worker_run(log_dir)
    worker_history = list_worker_runs(log_dir, limit=8)
    data_health: dict[str, Any] | None = None
    try:
        from nomadquant.shadow.data_ops import data_check

        data_health = data_check(settings, feed="sip")
    except Exception as exc:  # noqa: BLE001
        data_health = {"status": "ERROR", "reason": str(exc)[:300]}

    return {
        "market": market_info,
        "pending_intents": pending,
        "pending_intent_count": len(pending),
        "recovery_required": recovery_flag,
        "outbox_backlog": outbox_backlog,
        "last_worker_run": last_worker,
        "worker_runs": worker_history,
        "data_health": data_health,
        "alerts": alerts,
        "last_cycle": last_cycle,
        "cycle_count": cycle_count,
    }


@router.get("/timeline")
def shadow_timeline(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: str = Query(default=""),
) -> dict[str, Any]:
    store = _store(request)
    if store is None:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    status_filter = status or None
    items = store.list_cycles(limit=limit, offset=offset, status=status_filter)
    total = store.count_cycles(status=status_filter)
    enriched = []
    for c in items:
        intent_id = f"intent:{c['cycle_key']}"
        intent_tx = store.list_transitions(intent_id=intent_id, limit=20)
        transitions = [
            {"step": t.get("to_state", ""), "at": t.get("recorded_at", "")}
            for t in reversed(intent_tx)
        ]
        enriched.append(
            {
                **{
                    k: c.get(k)
                    for k in (
                        "id",
                        "cycle_key",
                        "created_at",
                        "mode",
                        "label",
                        "signal_session",
                        "fill_session",
                        "feed",
                        "symbol",
                        "status",
                        "intent",
                        "risk_verdict",
                        "evidence_hash",
                        "warnings",
                    )
                },
                "transitions": transitions,
            }
        )
    return {
        "items": enriched,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/cycles")
def shadow_cycles(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    store = _store(request)
    if store is None:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    return {
        "items": store.list_cycles(limit=limit, offset=offset),
        "total": store.count_cycles(),
        "limit": limit,
        "offset": offset,
    }


@router.get("/cycles/{cycle_id}")
def shadow_cycle_detail(cycle_id: int, request: Request) -> dict[str, Any]:
    store = _store(request)
    detail = None if store is None else store.get_cycle(cycle_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Shadow cycle not found.")
    return detail


@router.get("/equity")
def shadow_equity(
    request: Request, limit: int = Query(default=500, ge=1, le=5000)
) -> dict[str, Any]:
    store = _store(request)
    if store is None:
        return {"items": []}
    return {"items": store.equity_history(limit=limit)}


@router.get("/quality")
def shadow_quality(request: Request) -> dict[str, Any]:
    from nomadquant.quality import quality_report

    return quality_report(request.app.state.settings)


@router.get("/pilot")
def shadow_pilot(request: Request) -> dict[str, Any]:
    from nomadquant.shadow.pilot import forward_pilot_report

    return forward_pilot_report(request.app.state.settings)


@router.get("/cycles/{cycle_id}/verification")
def shadow_cycle_verification(cycle_id: int, request: Request) -> dict[str, Any]:
    from nomadquant.shadow.verify import verify_cycle

    return verify_cycle(request.app.state.settings, cycle_id)


@router.get("/preflight")
def shadow_preflight(request: Request) -> dict[str, Any]:
    return run_preflight(request.app.state.settings)


@router.get("/reconcile")
def shadow_reconcile(request: Request) -> dict[str, Any]:
    return run_reconcile(request.app.state.settings)
