"""Read-only observability routes."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from nomadquant.audit import COMPONENTS, LEVELS, STATUSES, AuditLog

router = APIRouter(prefix="/api/observability")


class AuditEventModel(BaseModel):
    id: int
    created_at: str
    event_type: str
    event_level: str
    component: str
    status: str
    title: str
    summary: str
    correlation_id: str
    run_id: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message_safe: str | None = None


class RunModel(BaseModel):
    id: int
    created_at: str
    finished_at: str | None = None
    run_type: str
    component: str
    status: str
    title: str
    summary: str
    correlation_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message_safe: str | None = None


class DecisionTraceModel(BaseModel):
    id: int
    created_at: str
    source_type: str
    symbols: list[str]
    decision_action: str
    proposed_notional: str | None = None
    decision_status: str
    rationale_summary: str
    evidence_summary: str
    warnings: str
    market_data_snapshot: str
    research_note_ids: str
    backtest_id: str | None = None
    risk_decision_id: str | None = None
    broker_event_id: str | None = None
    model_provider: str | None = None
    confidence: str | None = None
    explanation: dict[str, Any] = Field(default_factory=dict)


class EventPage(BaseModel):
    items: list[AuditEventModel]
    total: int
    limit: int
    offset: int


class RunPage(BaseModel):
    items: list[RunModel]
    total: int
    limit: int
    offset: int


class DecisionPage(BaseModel):
    items: list[DecisionTraceModel]
    total: int
    limit: int
    offset: int


class ObservabilityOverview(BaseModel):
    event_count: int
    warning_count: int
    error_count: int
    run_count: int
    decision_trace_count: int
    recent_events: list[AuditEventModel]


class SystemHealthModel(BaseModel):
    api_ok: bool
    trading_mode: str
    allow_order_submission: bool
    api_host: str
    alpaca_base_url: str
    operational_database_ok: bool
    market_data_database_present: bool
    broker_status: str
    broker_message: str | None
    last_event_at: str | None
    event_count: int
    run_count: int
    decision_trace_count: int


def _audit(request: Request) -> AuditLog:
    audit: AuditLog = request.app.state.audit
    return audit


def _bounds(limit: int, offset: int) -> tuple[int, int]:
    return min(max(limit, 1), 200), max(offset, 0)


def _check(value: str | None, allowed: frozenset[str], label: str) -> None:
    if value is not None and value not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported {label}.")


@router.get("/overview", response_model=ObservabilityOverview)
def overview(request: Request) -> ObservabilityOverview:
    audit = _audit(request)
    audit.mirror_market_imports(request.app.state.settings.market_data_path)
    counts = audit.counts()
    recent = [AuditEventModel.model_validate(item) for item in audit.recent_events()]
    return ObservabilityOverview(
        event_count=counts["events"],
        warning_count=counts["warnings"],
        error_count=counts["errors"],
        run_count=counts["runs"],
        decision_trace_count=counts["decision_traces"],
        recent_events=recent,
    )


@router.get("/events", response_model=EventPage)
def events(
    request: Request,
    component: str | None = None,
    status: str | None = None,
    level: str | None = Query(default=None),
    event_type: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> EventPage:
    _check(component, COMPONENTS, "component")
    _check(status, STATUSES, "status")
    _check(level, LEVELS, "level")
    bounded_limit, bounded_offset = _bounds(limit, offset)
    filters = {
        key: value
        for key, value in {
            "component": component or "",
            "status": status or "",
            "event_level": level or "",
            "event_type": event_type or "",
            "start": start or "",
            "end": end or "",
        }.items()
        if value
    }
    items, total = _audit(request).list_events(filters, bounded_limit, bounded_offset)
    return EventPage(
        items=[AuditEventModel.model_validate(item) for item in items],
        total=total,
        limit=bounded_limit,
        offset=bounded_offset,
    )


@router.get("/events/{event_id}", response_model=AuditEventModel)
def event_detail(event_id: int, request: Request) -> AuditEventModel:
    item = _audit(request).get_event(event_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Event not found.")
    return AuditEventModel.model_validate(item)


@router.get("/runs", response_model=RunPage)
def runs(
    request: Request,
    component: str | None = None,
    status: str | None = None,
    run_type: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> RunPage:
    _check(component, COMPONENTS, "component")
    _check(status, STATUSES, "status")
    audit = _audit(request)
    audit.mirror_market_imports(request.app.state.settings.market_data_path)
    bounded_limit, bounded_offset = _bounds(limit, offset)
    filters = {
        key: value
        for key, value in {
            "component": component or "",
            "status": status or "",
            "run_type": run_type or "",
            "start": start or "",
            "end": end or "",
        }.items()
        if value
    }
    items, total = audit.list_runs(filters, bounded_limit, bounded_offset)
    return RunPage(
        items=[RunModel.model_validate(item) for item in items],
        total=total,
        limit=bounded_limit,
        offset=bounded_offset,
    )


@router.get("/runs/{run_id}", response_model=RunModel)
def run_detail(run_id: int, request: Request) -> RunModel:
    item = _audit(request).get_run(run_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return RunModel.model_validate(item)


@router.get("/decision-traces", response_model=DecisionPage)
def decision_traces(
    request: Request,
    limit: int = 50,
    offset: int = 0,
) -> DecisionPage:
    bounded_limit, bounded_offset = _bounds(limit, offset)
    items, total = _audit(request).list_decisions(bounded_limit, bounded_offset)
    return DecisionPage(
        items=[DecisionTraceModel.model_validate(item) for item in items],
        total=total,
        limit=bounded_limit,
        offset=bounded_offset,
    )


@router.get("/decision-traces/{decision_id}", response_model=DecisionTraceModel)
def decision_detail(decision_id: int, request: Request) -> DecisionTraceModel:
    item = _audit(request).get_decision(decision_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Decision trace not found.")
    return DecisionTraceModel.model_validate(item)


@router.get("/system-health", response_model=SystemHealthModel)
def system_health(request: Request) -> SystemHealthModel:
    from nomadquant.broker.alpaca import AlpacaReadOnlyBroker
    from nomadquant.db import database_ok

    settings = request.app.state.settings
    audit = _audit(request)
    audit.mirror_market_imports(settings.market_data_path)
    counts = audit.counts()
    recent = audit.recent_events(1)
    broker: AlpacaReadOnlyBroker = request.app.state.broker
    account = broker.account()
    return SystemHealthModel(
        api_ok=True,
        trading_mode="paper",
        allow_order_submission=False,
        api_host=settings.api_host,
        alpaca_base_url=settings.alpaca_base_url,
        operational_database_ok=database_ok(settings.database_path),
        market_data_database_present=Path(settings.market_data_path).exists(),
        broker_status=account.status,
        broker_message=account.message,
        last_event_at=None if not recent else recent[0]["created_at"],
        event_count=counts["events"],
        run_count=counts["runs"],
        decision_trace_count=counts["decision_traces"],
    )
