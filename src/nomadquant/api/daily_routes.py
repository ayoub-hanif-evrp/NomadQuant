"""Read-only daily pilot status. This route cannot submit an order."""

from typing import Any

from fastapi import APIRouter, Request

from nomadquant.daily.cycle import daily_status

router = APIRouter(prefix="/api/daily")


@router.get("/status")
def daily_pilot_status(request: Request) -> dict[str, Any]:
    report = daily_status(request.app.state.settings)
    report["broker_orders_submitted_by_this_request"] = False
    return report
