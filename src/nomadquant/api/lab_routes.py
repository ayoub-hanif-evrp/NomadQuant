"""Isolated simulation lab. POST runs one session. It cannot place an order."""

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from nomadquant.api.csrf import require_local_mutation
from nomadquant.lab.runner import SCENARIOS, latest_session, run_lab

router = APIRouter(prefix="/api/lab")


class RunBody(BaseModel):
    scenario: Literal[
        "replay_3m",
        "replay_12m",
        "replay_3y",
        "replay_full",
        "mechanics",
        "crash_stress",
        "observed_quote",
    ] = "replay_12m"


@router.get("/latest")
def lab_latest(request: Request) -> dict[str, Any]:
    found = latest_session(request.app.state.settings)
    return {"session": found, "broker_orders": False}


@router.post("/run")
def lab_run(body: RunBody, request: Request) -> dict[str, Any]:
    require_local_mutation(request)
    if body.scenario not in SCENARIOS:
        raise HTTPException(status_code=400, detail="Unknown simulation scenario.")
    try:
        return run_lab(request.app.state.settings, body.scenario)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
