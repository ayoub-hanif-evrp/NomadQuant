"""Read-only view of local agent runs. Cannot start runs or place orders."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from nomadquant.agents.benchmark import BENCHMARK_VERSION, BenchmarkStore
from nomadquant.agents.constants import PROMPT_VERSION, RUN_LABEL, TOOL_SCHEMA_VERSION
from nomadquant.agents.guarded_tools import ALLOWED_TOOLS
from nomadquant.agents.ollama import OllamaError, OllamaProvider
from nomadquant.agents.store import AgentStore

router = APIRouter(prefix="/api/agents")


def _store(request: Request) -> AgentStore | None:
    """Open the store only if it already exists. Reading never creates a database."""
    path = Path(request.app.state.settings.agents_path)
    return AgentStore(path) if path.exists() else None


@router.get("/status")
def agents_status(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    provider = getattr(request.app.state, "ollama_provider", None) or OllamaProvider(
        settings.ollama_base_url
    )
    store = _store(request)
    health = provider.health(timeout=1.5)
    models: list[dict[str, Any]] = []
    if health["available"]:
        try:
            models = provider.list_model_details(timeout=1.5)
        except OllamaError:
            models = [{"name": name} for name in health["models"]]
    return {
        "ollama": health,
        "configured_model": settings.ollama_model,
        "installed_models": models,
        "prompt_version": PROMPT_VERSION,
        "tool_schema_version": TOOL_SCHEMA_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "label": RUN_LABEL,
        "tools": sorted(ALLOWED_TOOLS),
        "order_tools_available": False,
        "trading_mode": "paper",
        "run_count": 0 if store is None else store.count_runs(),
    }


@router.get("/benchmarks")
def agent_benchmarks(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    path = Path(request.app.state.settings.agent_benchmark_path)
    if not path.exists():
        return {"items": [], "benchmark_version": BENCHMARK_VERSION}
    return {
        "items": BenchmarkStore(path).list_recent(limit=limit),
        "benchmark_version": BENCHMARK_VERSION,
    }


@router.get("/runs")
def agent_runs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    store = _store(request)
    if store is None:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    return {
        "items": store.list_runs(limit=limit, offset=offset),
        "total": store.count_runs(),
        "limit": limit,
        "offset": offset,
    }


@router.get("/runs/{run_id}")
def agent_run_detail(run_id: int, request: Request) -> dict[str, Any]:
    store = _store(request)
    detail = None if store is None else store.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Agent run not found.")
    return detail
