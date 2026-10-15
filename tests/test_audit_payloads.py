"""Audit payload fidelity: large JSON, merge on finish, secret redaction."""

import json

from nomadquant.audit import INLINE_PAYLOAD_LIMIT, AuditLog
from tests.conftest import make_settings


def test_large_payload_round_trips_as_valid_json(tmp_path) -> None:
    audit = AuditLog(tmp_path / "audit.db")
    blob = {"rows": ["x" * 200 for _ in range(100)], "note": "evidence"}
    encoded = json.dumps(blob)
    assert len(encoded.encode("utf-8")) > INLINE_PAYLOAD_LIMIT
    event_id = audit.record_event(
        event_type="research.evidence",
        event_level="info",
        component="research",
        status="succeeded",
        title="Evidence",
        summary="Large evidence stored.",
        payload=blob,
    )
    loaded = audit.get_event(event_id)
    assert loaded is not None
    assert loaded["payload"]["note"] == "evidence"
    assert len(loaded["payload"]["rows"]) == 100
    raw = json.dumps(loaded["payload"])
    json.loads(raw)


def test_finish_run_keeps_original_config(tmp_path) -> None:
    audit = AuditLog(tmp_path / "audit.db")
    run_id = audit.start_run(
        run_type="research_backtest",
        component="backtest",
        title="Run",
        summary="started",
        payload={
            "config": {"lookback": 252},
            "dataset": {"digest": "abc"},
            "hypothesis_id": "H1",
            "experiment_id": "E1",
        },
    )
    audit.finish_run(
        run_id,
        status="succeeded",
        summary="done",
        payload={"result": {"net_return": "0.1"}},
    )
    run = audit.get_run(run_id)
    assert run is not None
    assert run["payload"]["config"] == {"lookback": 252}
    assert run["payload"]["dataset"] == {"digest": "abc"}
    assert run["payload"]["hypothesis_id"] == "H1"
    assert run["payload"]["result"]["net_return"] == "0.1"


def test_sensitive_keys_and_secrets_are_redacted(tmp_path) -> None:
    secret = "PLANTED-RESEARCH-SECRET-55cd"
    settings = make_settings(tmp_path, alpaca_api_key=secret, alpaca_api_secret="other")
    audit = AuditLog(settings.database_path, settings.secret_values)
    event_id = audit.record_event(
        event_type="api.error",
        event_level="error",
        component="system",
        status="failed",
        title="fail",
        summary=f"saw {secret}",
        payload={"api_key": "should-not-store", "note": secret},
    )
    loaded = audit.get_event(event_id)
    assert loaded is not None
    assert secret not in loaded["summary"]
    assert loaded["payload"]["api_key"] == "[REDACTED]"
    assert secret not in json.dumps(loaded["payload"])


def test_artifact_survives_reopen(tmp_path) -> None:
    path = tmp_path / "audit.db"
    audit = AuditLog(path)
    blob = {"body": "y" * (INLINE_PAYLOAD_LIMIT + 100)}
    event_id = audit.record_event(
        event_type="research.evidence",
        event_level="info",
        component="research",
        status="succeeded",
        title="Evidence",
        summary="stored",
        payload=blob,
    )
    again = AuditLog(path)
    loaded = again.get_event(event_id)
    assert loaded is not None
    assert loaded["payload"]["body"].startswith("y")
