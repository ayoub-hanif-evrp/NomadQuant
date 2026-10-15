"""Audit log behavior. No network and no credentials."""

from fastapi.testclient import TestClient

from nomadquant.api.app import create_app
from nomadquant.audit import AuditLog
from tests.conftest import make_settings


def test_events_round_trip_and_filter(tmp_path) -> None:
    settings = make_settings(tmp_path)
    audit = AuditLog(settings.database_path)
    audit.record_event(
        event_type="broker.account.read",
        event_level="info",
        component="broker",
        status="succeeded",
        title="Account read",
        summary="Paper account read succeeded.",
    )
    audit.record_event(
        event_type="market_data.report",
        event_level="warning",
        component="market_data",
        status="warning",
        title="Report",
        summary="Coverage is incomplete.",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/api/observability/events", params={"component": "broker"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["component"] == "broker"
    assert body["items"][0]["summary"] == "Paper account read succeeded."


def test_decision_trace_shape_and_empty_default(tmp_path) -> None:
    settings = make_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        empty = client.get("/api/observability/decision-traces")
        missing = client.get("/api/observability/decision-traces/1")
    assert empty.status_code == 200
    assert empty.json()["total"] == 0
    assert empty.json()["items"] == []
    assert missing.status_code == 404
    audit = AuditLog(settings.database_path)
    audit.record_decision(
        source_type="strategy",
        symbols=["SPY"],
        decision_action="no_trade",
        decision_status="recorded",
        rationale_summary="No strategy is implemented.",
        evidence_summary="No evidence was produced.",
    )
    with TestClient(create_app(settings)) as client:
        listed = client.get("/api/observability/decision-traces")
        detail = client.get("/api/observability/decision-traces/1")
    assert listed.json()["total"] == 1
    assert detail.status_code == 200
    assert detail.json()["decision_action"] == "no_trade"
    assert detail.json()["symbols"] == ["SPY"]
    assert "rationale_summary" in detail.json()


def test_secret_is_redacted_from_the_audit_log(tmp_path) -> None:
    secret = "PLANTED-AUDIT-SECRET-22ab"
    settings = make_settings(tmp_path, alpaca_api_key=secret, alpaca_api_secret="other-secret")
    audit = AuditLog(settings.database_path, settings.secret_values)
    audit.record_event(
        event_type="api.error",
        event_level="error",
        component="system",
        status="failed",
        title="API request failed",
        summary=f"request carried {secret}",
        error_message_safe=f"body {secret}",
        payload={"note": secret},
    )
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/api/observability/events", params={"event_type": "api.error"})
    text = response.text
    assert secret not in text
    assert "[REDACTED]" in text


def test_runs_list_and_unknown_filter(tmp_path) -> None:
    settings = make_settings(tmp_path)
    audit = AuditLog(settings.database_path)
    run_id = audit.start_run(
        run_type="market_data_report",
        component="market_data",
        title="Report",
        summary="Started.",
    )
    audit.finish_run(run_id, status="succeeded", summary="Report finished.")
    app = create_app(settings)
    with TestClient(app) as client:
        listed = client.get("/api/observability/runs", params={"run_type": "market_data_report"})
        detail = client.get(f"/api/observability/runs/{run_id}")
        rejected = client.get("/api/observability/events", params={"component": "not-a-component"})
        overview = client.get("/api/observability/overview")
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1
    assert detail.json()["status"] == "succeeded"
    assert rejected.status_code == 400
    assert overview.json()["decision_trace_count"] == 0
    assert overview.json()["run_count"] >= 1
