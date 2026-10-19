"""Read-only Alpaca paper status. This route cannot submit an order."""

from typing import Any

from fastapi import APIRouter, Request

from nomadquant.broker.paper_pilot import paper_status

router = APIRouter(prefix="/api/paper")


@router.get("/status")
def paper_trading_status(request: Request) -> dict[str, Any]:
    report = paper_status(request.app.state.settings)
    report["broker_orders_submitted_by_this_request"] = False
    return report
