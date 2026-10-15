"""Read-only Risk Policy Lab endpoints. Never submit orders."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from nomadquant.risk.policy import POLICY_VERSION, RiskPolicy
from nomadquant.risk.store import RiskStore

router = APIRouter(prefix="/api/risk")


def _store(request: Request) -> RiskStore | None:
    path = Path(request.app.state.settings.risk_path)
    return RiskStore(path) if path.exists() else None


@router.get("/status")
def risk_status(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    policy = RiskPolicy()
    store = _store(request)
    return {
        "label": "risk_policy_lab",
        "is_broker_execution": False,
        "order_submission_enabled": False,
        "allow_order_submission": settings.allow_order_submission,
        "trading_mode": settings.trading_mode,
        "internal_capital_usd": settings.initial_virtual_capital_usd,
        "policy_version": POLICY_VERSION,
        "policy_hash": policy.policy_hash(),
        "policy": {
            "allowed_symbols": sorted(policy.allowed_symbols),
            "max_total_exposure": str(policy.max_total_exposure),
            "max_symbol_exposure": str(policy.max_symbol_exposure),
            "max_single_transaction_usd": str(policy.max_single_transaction_usd),
            "min_cash_reserve_usd": str(policy.min_cash_reserve_usd),
            "max_daily_modeled_loss_fraction": str(policy.max_daily_modeled_loss_fraction),
            "max_price_age_hours": policy.max_price_age.total_seconds() / 3600.0,
            "max_qty_decimals": policy.max_qty_decimals,
            "spread_bps": str(policy.spread_bps),
            "commission_usd": str(policy.commission_usd),
            "emergency_halt": policy.emergency_halt,
        },
        "evaluation_count": 0 if store is None else store.count(),
        "note": (
            "Hypothetical policy verdicts only. Alpaca paper equity is never used as "
            "available capital. No order path exists on this API."
        ),
    }


@router.get("/evaluations")
def risk_evaluations(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    store = _store(request)
    if store is None:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    return {
        "items": store.list(limit=limit, offset=offset),
        "total": store.count(),
        "limit": limit,
        "offset": offset,
    }


@router.get("/evaluations/{evaluation_id}")
def risk_evaluation_detail(evaluation_id: int, request: Request) -> dict[str, Any]:
    store = _store(request)
    detail = None if store is None else store.get_by_id(evaluation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Risk evaluation not found.")
    return detail
