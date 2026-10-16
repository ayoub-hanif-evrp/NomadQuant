"""Create and resolve internal-shadow approval requests. Not broker orders."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from nomadquant.approvals.mailer import deliver_approval_email, render_approval_message
from nomadquant.approvals.store import SCOPE, ApprovalStore, public_view, token_hash
from nomadquant.config import Settings


def create_approval_request(
    settings: Settings,
    *,
    instrument: str,
    action: str,
    quantity: str,
    notional_usd: str,
    why: str,
    risk_summary: str,
    caveats: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Store one request and deliver the review link. The raw token is not returned."""
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        raise ValueError("Approval clock must be timezone-aware.")
    request_id = secrets.token_hex(8)
    token = secrets.token_urlsafe(32)
    expires = clock + timedelta(minutes=settings.approval_ttl_minutes)
    store = ApprovalStore(settings.approval_path)
    store.insert(
        {
            "id": request_id,
            "status": "pending",
            "token_hash": token_hash(token),
            "instrument": instrument,
            "action": action,
            "quantity": quantity,
            "notional_usd": notional_usd,
            "why": why,
            "risk_summary": risk_summary,
            "caveats": caveats,
            "scope": SCOPE,
            "created_at": clock.isoformat(),
            "expires_at": expires.isoformat(),
        }
    )
    review_url = _review_url(settings, request_id, token)
    body = render_approval_message(
        request_id=request_id,
        instrument=instrument,
        action=action,
        quantity=quantity,
        notional_usd=notional_usd,
        why=why,
        risk_summary=risk_summary,
        caveats=caveats,
        review_url=review_url,
    )
    try:
        delivery = deliver_approval_email(
            settings,
            request_id=request_id,
            subject=f"NomadQuant shadow approval: {action} {instrument}",
            body=body,
        )
    except Exception as exc:  # noqa: BLE001
        delivery = {"delivery": "local_outbox", "path": "", "error": type(exc).__name__}
    store.add_audit(request_id, "email_" + delivery["delivery"], "Review link issued.")
    row = store.get(request_id)
    assert row is not None
    viewed = public_view(row, now=clock)
    viewed["delivery"] = delivery["delivery"]
    return viewed


def list_approval_requests(settings: Settings, *, now: datetime | None = None) -> dict[str, Any]:
    clock = now or datetime.now(UTC)
    store = ApprovalStore.open_readonly(settings.approval_path)
    if store is None:
        return {
            "initialized": False,
            "items": [],
            "scope": SCOPE,
            "broker_orders": False,
        }
    return {
        "initialized": True,
        "items": [public_view(row, now=clock) for row in store.list_requests()],
        "scope": SCOPE,
        "broker_orders": False,
    }


def approval_detail(
    settings: Settings,
    request_id: str,
    *,
    token: str,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    clock = now or datetime.now(UTC)
    store = ApprovalStore.open_readonly(settings.approval_path)
    if store is None:
        return None
    row = store.get(request_id)
    if row is None or row["token_hash"] != token_hash(token):
        return None
    viewed = public_view(row, now=clock)
    viewed["audit"] = store.audit_for(request_id)
    viewed["confirm_required"] = True
    return viewed


def decide_approval_request(
    settings: Settings,
    request_id: str,
    *,
    token: str,
    action: str,
    confirm: str,
    reason: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Consume a one-time token only after explicit confirmation."""
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        raise ValueError("Approval clock must be timezone-aware.")
    if action not in {"approve", "reject"}:
        raise ValueError("Action must be approve or reject.")
    preview = approval_detail(settings, request_id, token=token, now=clock)
    if preview is None:
        raise ValueError("Approval request was not found.")
    if confirm != "1":
        return {
            **preview,
            "applied": False,
            "note": "Confirmation is required before this token is used.",
        }
    store = ApprovalStore(settings.approval_path)
    row = store.get(request_id)
    assert row is not None
    if row["token_hash"] != token_hash(token):
        raise ValueError("Approval request was not found.")
    if row["status"] != "pending":
        raise ValueError("This approval token was already used.")
    expires = datetime.fromisoformat(str(row["expires_at"]))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires <= clock:
        store.decide(request_id, status="expired", reason="The approval window closed.", now=clock)
        updated = store.get(request_id)
        assert updated is not None
        viewed = public_view(updated, now=clock)
        viewed["audit"] = store.audit_for(request_id)
        viewed["applied"] = False
        return viewed
    status = "approved" if action == "approve" else "rejected"
    note = reason.strip() or (
        "Approved for a later internal shadow cycle. No broker order was sent."
        if status == "approved"
        else "Rejected. No shadow apply and no broker order."
    )
    store.decide(request_id, status=status, reason=note, now=clock)
    updated = store.get(request_id)
    assert updated is not None
    viewed = public_view(updated, now=clock)
    viewed["audit"] = store.audit_for(request_id)
    viewed["applied"] = False
    viewed["broker_orders"] = False
    return viewed


def _review_url(settings: Settings, request_id: str, token: str) -> str:
    base = settings.approval_public_base_url.rstrip("/")
    query = urlencode({"token": token})
    return f"{base}/approvals/respond/{request_id}?{query}"
