"""Internal shadow approval email is one-time, expiring, and not a broker order."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from nomadquant.api.app import create_app
from nomadquant.approvals.service import create_approval_request
from tests.conftest import make_settings


def _post(client: TestClient, request_id: str, token: str, **fields: str) -> object:
    body = {"token": token, "action": "approve", "confirm": "0", "reason": ""}
    body.update(fields)
    return client.post(
        f"/api/approvals/{request_id}/decide",
        json=body,
        headers={"Origin": "http://127.0.0.1:3000", "X-NomadQuant-Intent": "mutate"},
    )


def _token(letter: str) -> str:
    for line in letter.splitlines():
        if "token=" in line:
            return line.split("token=", 1)[1].strip()
    raise AssertionError("review link did not include a token")


def _proposal(tmp_path: Path, **overrides: object) -> tuple[object, dict[str, object]]:
    now = datetime.now(UTC)
    if "now" in overrides:
        now = overrides.pop("now")  # type: ignore[assignment]
    preview_hash = str(overrides.pop("preview_hash", "") or "")
    settings = make_settings(
        tmp_path,
        approval_path=str(tmp_path / "approvals.sqlite"),
        approval_outbox_dir=str(tmp_path / "outbox"),
        approval_ttl_minutes=30,
        approval_public_base_url="http://127.0.0.1:3000",
        **overrides,
    )
    created = create_approval_request(
        settings,
        instrument="SPY",
        action="buy",
        quantity="0.25",
        notional_usd="50",
        why="Month-start momentum is positive inside the paper shadow ledger.",
        risk_summary="Cash reserve held. No broker route.",
        caveats="Delayed hypothetical daily open. Not a live order.",
        now=now,
        preview_hash=preview_hash,
    )
    return settings, created


def test_missing_inbox_does_not_create_a_database(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, approval_path=str(tmp_path / "missing.sqlite"))
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/api/approvals/inbox")
    assert response.status_code == 200
    assert response.json()["initialized"] is False
    assert response.json()["broker_orders"] is False
    assert not Path(settings.approval_path).exists()


def test_local_outbox_and_one_time_decision(tmp_path: Path) -> None:
    settings, created = _proposal(tmp_path)
    assert created["broker_orders"] is False
    assert created["delivery"] == "local_outbox"
    assert "token" not in created
    letter = Path(settings.approval_outbox_dir, f"{created['id']}.txt").read_text(encoding="utf-8")
    assert "SPY" in letter
    assert "This is not a broker order" in letter
    assert "does not submit an Alpaca order" in letter
    token = _token(letter)
    app = create_app(settings)
    with TestClient(app) as client:
        preview = _post(client, str(created["id"]), token)
        assert preview.status_code == 200
        assert preview.json()["status"] == "pending"
        assert preview.json()["applied"] is False
        first = _post(client, str(created["id"]), token, confirm="1")
        assert first.status_code == 200
        body = first.json()
        assert body["status"] == "approved"
        assert body["broker_orders"] is False
        assert body["applied"] is False
        assert body["shadow_grant_issued"] is False
        assert any(row["event"] == "approved" for row in body["audit"])
        replay = _post(client, str(created["id"]), token, confirm="1")
        assert replay.status_code == 409
        scanned = client.get(f"/api/approvals/{created['id']}/decide", params={"token": token})
        assert scanned.status_code == 405


def test_reject_and_expiry_are_audited(tmp_path: Path) -> None:
    settings, created = _proposal(tmp_path)
    letter = Path(settings.approval_outbox_dir, f"{created['id']}.txt").read_text(encoding="utf-8")
    token = _token(letter)
    app = create_app(settings)
    with TestClient(app) as client:
        rejected = _post(
            client,
            str(created["id"]),
            token,
            action="reject",
            confirm="1",
            reason="Not this week.",
        )
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "rejected"
        assert rejected.json()["decision_reason"] == "Not this week."
        assert any(row["event"] == "rejected" for row in rejected.json()["audit"])

    expired_settings, expired = _proposal(
        tmp_path / "later",
        now=datetime.now(UTC) - timedelta(hours=2),
    )
    expired_settings.approval_ttl_minutes = 30
    letter = Path(expired_settings.approval_outbox_dir, f"{expired['id']}.txt").read_text(
        encoding="utf-8"
    )
    token = _token(letter)
    app = create_app(expired_settings)
    with TestClient(app) as client:
        response = _post(client, str(expired["id"]), token, confirm="1")
        assert response.status_code == 200
        assert response.json()["status"] == "expired"
        assert any(row["event"] == "expired" for row in response.json()["audit"])


def test_smtp_delivery_does_not_put_the_password_in_the_letter(
    tmp_path: Path, monkeypatch: object
) -> None:
    sent: dict[str, object] = {}

    class _FakeSmtp:
        def __init__(self, host: str, port: int, timeout: int = 10) -> None:
            sent["host"] = host
            sent["port"] = port
            sent["timeout"] = timeout

        def __enter__(self) -> "_FakeSmtp":
            return self

        def __exit__(self, *_args: object) -> bool:
            return False

        def starttls(self) -> None:
            sent["tls"] = True

        def login(self, user: str, password: str) -> None:
            sent["user"] = user
            sent["password"] = password

        def send_message(self, message: object) -> None:
            sent["to"] = message["To"]  # type: ignore[index]

    monkeypatch.setattr("nomadquant.approvals.mailer.smtplib.SMTP", _FakeSmtp)  # type: ignore[attr-defined]
    settings, created = _proposal(
        tmp_path / "smtp",
        smtp_host="127.0.0.1",
        smtp_port=2525,
        smtp_username="nomad",
        smtp_password="local-secret",
        approval_email_to="owner@localhost",
    )
    letter = Path(settings.approval_outbox_dir, f"{created['id']}.txt").read_text(encoding="utf-8")
    assert created.get("error") is None, created
    assert created["delivery"] == "smtp"
    assert sent["tls"] is True
    assert sent["password"] == "local-secret"
    assert "local-secret" not in letter
    assert "token=" in letter
    assert not Path(settings.shadow_path).exists()


def test_missing_mutation_header_does_not_consume_the_token(tmp_path: Path) -> None:
    settings, created = _proposal(tmp_path)
    letter = Path(settings.approval_outbox_dir, f"{created['id']}.txt").read_text(encoding="utf-8")
    token = _token(letter)
    app = create_app(settings)
    with TestClient(app) as client:
        blocked = client.post(
            f"/api/approvals/{created['id']}/decide",
            json={"token": token, "action": "approve", "confirm": "1"},
        )
        assert blocked.status_code == 403
        inbox = client.get("/api/approvals/inbox")
    assert inbox.json()["items"][0]["status"] == "pending"


def test_bound_approval_rechecks_the_shadow_preview(tmp_path: Path, monkeypatch: object) -> None:
    seen: dict[str, str] = {}

    def _confirm(settings: object, approval: str) -> dict[str, object]:
        seen["approval"] = approval
        return {
            "status": "CONFIRMATION_ACCEPTED",
            "applied": False,
            "broker_orders": False,
            "stored": True,
        }

    monkeypatch.setattr("nomadquant.shadow.pilot.confirm_pilot_start", _confirm)  # type: ignore[attr-defined]
    settings, created = _proposal(tmp_path / "bound", preview_hash="abc123")
    letter = Path(settings.approval_outbox_dir, f"{created['id']}.txt").read_text(encoding="utf-8")
    token = _token(letter)
    app = create_app(settings)
    with TestClient(app) as client:
        refused = _post(client, str(created["id"]), token, confirm="1")
    # The patch is on the service function, which the route imports at call time.
    assert refused.status_code == 200
    assert refused.json()["shadow_grant_issued"] is True
    assert refused.json()["applied"] is False
    assert seen["approval"] == "abc123"
