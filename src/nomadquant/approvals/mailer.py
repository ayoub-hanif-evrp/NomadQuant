"""Send an approval email, or keep a local preview when SMTP is not configured."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from pathlib import Path

from nomadquant.config import Settings


def render_approval_message(
    *,
    request_id: str,
    instrument: str,
    action: str,
    quantity: str,
    notional_usd: str,
    why: str,
    risk_summary: str,
    caveats: str,
    review_url: str,
) -> str:
    return "\n".join(
        [
            "NomadQuant internal shadow approval",
            "",
            "This is not a broker order. Approving records your permission only.",
            "It does not submit an Alpaca order and does not bypass risk checks.",
            "",
            f"Instrument: {instrument}",
            f"Proposed action: {action}",
            f"Quantity: {quantity}",
            f"Notional: ${notional_usd}",
            f"Why: {why}",
            f"Risk checks: {risk_summary}",
            f"Caveats: {caveats}",
            "",
            "The review link is http://127.0.0.1 and only works on this computer.",
            "A phone or another machine cannot open it. GET never approves.",
            "",
            f"Review and confirm: {review_url}",
            f"Request: {request_id}",
        ]
    )


SMTP_TEST_CONFIRM = "SEND_HARMLESS_SMTP_TEST"


def send_harmless_smtp_test(settings: Settings, *, confirm: str) -> dict[str, str]:
    """Send one non-financial test after the exact phrase. Does not approve or trade."""
    if confirm != SMTP_TEST_CONFIRM:
        raise ValueError("Refusing to send until the exact confirmation phrase is provided.")
    if not settings.smtp_host.strip() or not settings.approval_email_to.strip():
        return {"sent": "false", "reason": "smtp_not_configured"}
    body = "\n".join(
        [
            "NomadQuant SMTP test.",
            "This message does not approve a proposal and does not place an order.",
            "Approval links use http://127.0.0.1 and open only on this computer.",
        ]
    )
    delivery = deliver_approval_email(
        settings,
        request_id="smtp-test",
        subject="NomadQuant SMTP test",
        body=body,
    )
    return {"sent": "true" if delivery["delivery"] == "smtp" else "false", **delivery}


def deliver_approval_email(
    settings: Settings,
    *,
    request_id: str,
    subject: str,
    body: str,
) -> dict[str, str]:
    """Use SMTP when it is configured. Otherwise write a local outbox file."""
    outbox = Path(settings.approval_outbox_dir)
    outbox.mkdir(parents=True, exist_ok=True)
    preview = outbox / f"{request_id}.txt"
    preview.write_text(body, encoding="utf-8")
    host = settings.smtp_host.strip()
    recipient = settings.approval_email_to.strip()
    if not host or not recipient:
        return {"delivery": "local_outbox", "path": str(preview)}
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.approval_email_from
    message["To"] = recipient
    message.set_content(body)
    with smtplib.SMTP(host, settings.smtp_port, timeout=10) as client:
        client.starttls()
        password = ""
        if settings.smtp_password is not None:
            password = settings.smtp_password.get_secret_value()
        if settings.smtp_username and password:
            client.login(settings.smtp_username, password)
        client.send_message(message)
    return {"delivery": "smtp", "path": str(preview)}
