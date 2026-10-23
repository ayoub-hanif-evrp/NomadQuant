"""Post-decision notices. A missing SMTP server is not reported as delivered."""

from __future__ import annotations

from typing import Any

from nomadquant.config import Settings
from nomadquant.daily.store import mark_notice, notice_body, notice_status


def deliver_notice(settings: Settings, notice_id: int) -> dict[str, Any]:
    stored = notice_body(settings.daily_path, notice_id)
    subject, body = stored if stored is not None else ("NomadQuant daily paper notice", "")
    if not settings.smtp_host.strip() or not settings.approval_email_to.strip():
        mark_notice(settings.daily_path, notice_id, status="not_configured")
        return {"sent": False, "status": "not_configured", "attempts": 1}
    try:
        from nomadquant.approvals.mailer import deliver_approval_email

        result = deliver_approval_email(
            settings,
            request_id=f"daily-{notice_id}",
            subject=subject,
            body=body,
        )
    except Exception as exc:  # noqa: BLE001 — SMTP text can contain a credential
        mark_notice(settings.daily_path, notice_id, status="delivery_failed")
        return {"sent": False, "status": "delivery_failed", "error_type": type(exc).__name__}
    status = "delivered" if result.get("delivery") == "smtp" else "delivery_failed"
    mark_notice(settings.daily_path, notice_id, status=status)
    current = notice_status(settings.daily_path)
    return {"sent": status == "delivered", "status": status, "attempts": current.get("attempts")}
