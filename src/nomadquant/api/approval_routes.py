"""Read and confirm internal shadow approvals. Every route is GET."""

from fastapi import APIRouter, HTTPException, Query, Request

from nomadquant.approvals.service import (
    approval_detail,
    decide_approval_request,
    list_approval_requests,
)

router = APIRouter(prefix="/api/approvals")


@router.get("/inbox")
def list_inbox(request: Request) -> dict[str, object]:
    return list_approval_requests(request.app.state.settings)


@router.get("/{request_id}")
def read_request(
    request_id: str,
    request: Request,
    token: str = Query(default=""),
) -> dict[str, object]:
    if not token:
        raise HTTPException(status_code=404, detail="Approval request was not found.")
    found = approval_detail(request.app.state.settings, request_id, token=token)
    if found is None:
        raise HTTPException(status_code=404, detail="Approval request was not found.")
    return found


@router.get("/{request_id}/decide")
def decide_request(
    request_id: str,
    request: Request,
    token: str = Query(default=""),
    action: str = Query(default="approve"),
    confirm: str = Query(default="0"),
    reason: str = Query(default=""),
) -> dict[str, object]:
    try:
        return decide_approval_request(
            request.app.state.settings,
            request_id,
            token=token,
            action=action,
            confirm=confirm,
            reason=reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
