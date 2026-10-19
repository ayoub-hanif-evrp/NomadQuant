"""The simulation lab stays off the forward ledger."""

from pathlib import Path

from fastapi.testclient import TestClient

from nomadquant.api.app import create_app
from nomadquant.lab.runner import run_lab
from tests.conftest import make_settings

_HEADERS = {"Origin": "http://127.0.0.1:3000", "X-NomadQuant-Intent": "mutate"}


def test_mechanics_and_crash_recovery_stay_isolated(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    forward = Path(settings.shadow_path)
    forward.write_bytes(b"forward-sentinel")
    result = run_lab(settings, "crash_stress")
    assert forward.read_bytes() == b"forward-sentinel"
    assert result["forward_ledger_touched"] is False
    assert result["label"] == "SYNTHETIC MECHANICS TEST"
    assert result["broker_orders"] is False
    assert result["buys"] >= 1
    assert result["sells"] >= 1
    assert any(item["decision"] == "duplicate_prevented" for item in result["events"])
    assert any(item["decision"] == "recovery" for item in result["events"])
    assert any(item["risk_verdict"] == "REJECT" for item in result["events"])
    approval = result["approval"]
    assert approval["delivery"] == "local_outbox"
    assert approval["smtp_used"] is False
    assert [item["result"] for item in approval["requests"]] == ["approved", "rejected", "expired"]
    assert approval["token_reuse_blocked"] is True
    assert result["verification"]["checked"] >= 1
    assert result["verification"]["passed"] == result["verification"]["checked"]
    assert result["starting_usd"] == "100"


def test_quote_lab_does_not_invent_a_strategy_signal(tmp_path: Path) -> None:
    result = run_lab(make_settings(tmp_path), "observed_quote")
    assert result["strategy_signal_created"] is False
    assert result["ledger_mutated"] is False
    assert result["buys"] == 0
    late = next(item for item in result["events"] if item["decision"] == "retrieved_after_decision")
    assert late["status"] == "NO_FILL"
    stale = next(item for item in result["events"] if item["decision"] == "stale")
    assert stale["status"] == "WAIT"
    assert stale["risk_reasons"] == ["quote_older_than_observed_policy"]
    assert result["live_quote"]["status"] == "NOT_RUN"


def test_lab_route_refuses_a_cross_site_post(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        missing = client.post("/api/lab/run", json={"scenario": "observed_quote"})
        assert missing.status_code == 403
        allowed = client.post(
            "/api/lab/run",
            json={"scenario": "observed_quote"},
            headers=_HEADERS,
        )
        assert allowed.status_code == 200
        body = allowed.json()
        assert body["broker_orders"] is False
        assert body["forward_ledger_touched"] is False
