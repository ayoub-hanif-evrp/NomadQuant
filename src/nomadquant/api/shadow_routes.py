"""Read-only shadow portfolio and cycle APIs. No order submission."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from nomadquant.shadow.store import ShadowStore

router = APIRouter(prefix="/api/shadow")


def _store(request: Request) -> ShadowStore | None:
    path = Path(request.app.state.settings.shadow_path)
    return ShadowStore(path) if path.exists() else None


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
            "note": "Shadow ledger not created yet. Run nomadquant-shadow cycle.",
        }
    snap = store.snapshot()
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
        "note": (
            "Internal $100 shadow ledger only. Values are not Alpaca paper profits "
            "and no broker orders are submitted."
        ),
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
