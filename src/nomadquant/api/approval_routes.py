"""Read and confirm internal shadow approvals. Decide is POST and does not trade."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from nomadquant.api.csrf import require_local_mutation
from nomadquant.approvals.service import (
    approval_detail,
    decide_approval_request,
    list_approval_requests,
)

router = APIRouter(prefix="/api/approvals")


class DecideBody(BaseModel):
    token: str = ""
    action: str = "approve"
    confirm: str = "0"
    reason: str = Field(default="", max_length=300)


@router.get("/inbox")
def list_inbox(request: Request) -> dict[str, Any]:
    return list_approval_requests(request.app.state.settings)


@router.get("/{request_id}")
def read_request(
    request_id: str,
    request: Request,
    token: str = Query(default=""),
) -> dict[str, Any]:
    if not token:
        raise HTTPException(status_code=404, detail="Approval request was not found.")
    found = approval_detail(request.app.state.settings, request_id, token=token)
    if found is None:
        raise HTTPException(status_code=404, detail="Approval request was not found.")
    return found


@router.post("/{request_id}/decide")
def decide_request(request_id: str, body: DecideBody, request: Request) -> dict[str, Any]:
    require_local_mutation(request)
    try:
        return decide_approval_request(
            request.app.state.settings,
            request_id,
            token=body.token,
            action=body.action,
            confirm=body.confirm,
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
