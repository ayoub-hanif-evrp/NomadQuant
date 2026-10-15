"""Read-only research lab API. Does not submit broker orders."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from nomadquant.research.replay import replay_run
from nomadquant.research.store import ResearchStore

router = APIRouter(prefix="/api/research")


class ExperimentSummary(BaseModel):
    experiment_id: str
    hypothesis_id: str
    title: str
    description: str
    citations: list[str]
    created_at: str


class RunSummary(BaseModel):
    id: int
    experiment_id: str
    created_at: str
    finished_at: str | None
    status: str
    git_commit: str | None
    engine_version: str
    dataset_fingerprint: str
    outcome_summary: str
    caveats: list[str]
    label: str = "backtest"
    is_paper_trading: bool = False
    is_broker_execution: bool = False


def _store(request: Request) -> ResearchStore:
    return ResearchStore(request.app.state.settings.research_path)


@router.get("/experiments")
def experiments(request: Request) -> dict[str, Any]:
    items = _store(request).list_experiments()
    return {"items": items, "total": len(items)}


@router.get("/experiments/{experiment_id}")
def experiment_detail(experiment_id: str, request: Request) -> dict[str, Any]:
    item = _store(request).get_experiment(experiment_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Experiment not found.")
    runs = _store(request).list_runs(experiment_id)
    return {**item, "runs": runs}


@router.get("/runs")
def runs(
    request: Request,
    experiment_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    items = _store(request).list_runs(experiment_id)[:limit]
    return {"items": items, "total": len(items)}


@router.get("/runs/{run_id}")
def run_detail(run_id: int, request: Request) -> dict[str, Any]:
    item = _store(request).get_run(run_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Research run not found.")
    store = _store(request)
    return {
        **item,
        "metrics": store.metrics(run_id),
        "research_mode": item["config"].get("research_mode", "price_only"),
    }


@router.get("/runs/{run_id}/equity")
def run_equity(
    run_id: int,
    request: Request,
    strategy_id: str | None = None,
) -> dict[str, Any]:
    if _store(request).get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Research run not found.")
    items = _store(request).equity(run_id, strategy_id)
    return {"items": items, "total": len(items)}


@router.get("/runs/{run_id}/trades")
def run_trades(
    run_id: int,
    request: Request,
    strategy_id: str | None = None,
) -> dict[str, Any]:
    if _store(request).get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Research run not found.")
    items = _store(request).trades(run_id, strategy_id)
    return {"items": items, "total": len(items), "note": "Simulated fills only. Not broker orders."}


@router.get("/runs/{run_id}/decisions")
def run_decisions(
    run_id: int,
    request: Request,
    strategy_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    if _store(request).get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Research run not found.")
    items = _store(request).decisions(run_id, strategy_id)
    page = items[offset : offset + limit]
    return {
        "items": page,
        "total": len(items),
        "limit": limit,
        "offset": offset,
        "note": "Simulated backtest decisions. Not Alpaca paper orders. Not agent decisions.",
    }


@router.get("/decisions/{decision_id}")
def decision_detail(decision_id: int, request: Request) -> dict[str, Any]:
    item = _store(request).get_decision(decision_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Decision not found.")
    return item


@router.get("/runs/{run_id}/replay")
def run_replay(run_id: int, request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    try:
        return replay_run(
            run_id,
            research_path=settings.research_path,
            market_path=settings.market_data_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
