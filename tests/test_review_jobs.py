"""The web "Run research review" button, end to end, with a scripted local provider."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nomadquant.agents import AgentStore, AgentStoreError
from nomadquant.api.app import create_app
from tests.conftest import make_settings
from tests.test_agents import Env, FakeProvider, build_env, happy_script

_HEADERS = {"Origin": "http://127.0.0.1:3000", "X-NomadQuant-Intent": "mutate"}
_BODY = {"model": "fake-model", "confirm": "RUN_LOCAL_RESEARCH_REVIEW"}


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return build_env(tmp_path)


class LocalProvider(FakeProvider):
    """A FakeProvider that also answers the health check the web route performs."""

    def __init__(self, script: dict[str, Any], *, available: bool = True) -> None:
        super().__init__(script)
        self.available = available

    def health(self, timeout: float = 2.0) -> dict[str, Any]:
        return {
            "available": self.available,
            "models": ["fake-model"] if self.available else [],
            "error": "" if self.available else "down",
        }

    def model_digest(self, model: str, timeout: float = 5.0) -> str:
        return "sha256:fake"


class CrashingProvider(LocalProvider):
    def chat_json(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("GPU driver vanished")


def _client(env: Env, provider: Any) -> TestClient:
    app = create_app(make_settings(env.tmp))
    app.state.ollama_provider = provider
    return TestClient(app)


def _wait_for_job(client: TestClient, job_id: int, timeout: float = 20.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/agents/jobs/{job_id}").json()
        if job["status"] not in {"queued", "running"}:
            return dict(job)
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} never finished")


def test_button_runs_researcher_skeptic_reviewer_to_completion(env: Env) -> None:
    provider = LocalProvider(happy_script(env))
    with _client(env, provider) as client:
        started = client.post(
            "/api/agents/reviews", json={**_BODY, "research_run_id": env.run_id}, headers=_HEADERS
        )
        assert started.status_code == 200, started.text
        body = started.json()
        assert body["started"] is True
        assert body["broker_orders"] is False
        assert body["job"]["status"] in {"queued", "running", "succeeded"}
        job = _wait_for_job(client, int(body["job_id"]))
        detail = client.get(f"/api/agents/runs/{job['agent_run_id']}").json()

    assert job["status"] == "succeeded", job
    assert job["model_digest"] == "sha256:fake"
    assert job["dataset_fingerprint"]
    assert [stage["name"] for stage in detail["stages"]] == [
        "researcher",
        "skeptic",
        "reviewer",
        "memo",
    ]
    assert all(stage["status"] == "succeeded" for stage in detail["stages"])
    assert detail["status"] == "succeeded"
    assert detail["verdict"] in {"evidence_supported", "insufficient_evidence"}

    first_message = {role: messages[1]["content"] for role, messages in reversed(provider.calls)}
    assert "researcher_report" in first_message["skeptic"]
    assert "researcher_report" in first_message["reviewer"]
    assert "skeptic_report" in first_message["reviewer"]
    assert any(call["tool_name"] == "verify_backtest" for call in detail["tool_calls"])


def test_invented_number_from_the_button_is_flagged(env: Env) -> None:
    provider = LocalProvider(happy_script(env, net_return="9.99"))
    with _client(env, provider) as client:
        started = client.post(
            "/api/agents/reviews", json={**_BODY, "research_run_id": env.run_id}, headers=_HEADERS
        )
        job = _wait_for_job(client, int(started.json()["job_id"]))
        detail = client.get(f"/api/agents/runs/{job['agent_run_id']}").json()
    assert job["status"] == "succeeded"
    assert detail["verdict"] == "verification_failed"
    assert any("net_return" in item for item in detail["result"]["rejected_claims"])


def test_a_crash_is_recorded_as_failed_not_running(env: Env) -> None:
    with _client(env, CrashingProvider(happy_script(env))) as client:
        started = client.post(
            "/api/agents/reviews", json={**_BODY, "research_run_id": env.run_id}, headers=_HEADERS
        )
        job = _wait_for_job(client, int(started.json()["job_id"]))
        detail = client.get(f"/api/agents/runs/{job['agent_run_id']}").json()
    assert job["status"] == "failed"
    assert "GPU driver vanished" in job["error_message_safe"]
    assert detail["status"] == "failed"
    assert all(stage["status"] != "running" for stage in detail["stages"])


@pytest.mark.parametrize(
    ("provider_available", "run_offset", "status"),
    [(False, 0, 503), (True, 999, 404)],
)
def test_refusals_happen_before_any_job_is_saved(
    env: Env, provider_available: bool, run_offset: int, status: int
) -> None:
    provider = LocalProvider(happy_script(env), available=provider_available)
    with _client(env, provider) as client:
        response = client.post(
            "/api/agents/reviews",
            json={**_BODY, "research_run_id": env.run_id + run_offset},
            headers=_HEADERS,
        )
        jobs = client.get("/api/agents/jobs").json()["items"]
    assert response.status_code == status
    assert jobs == []
    assert provider.calls == []


def test_stale_market_data_is_refused(env: Env, monkeypatch: Any) -> None:
    monkeypatch.setattr("nomadquant.agents.jobs.live_market_digest", lambda *_a: "different")
    with _client(env, LocalProvider(happy_script(env))) as client:
        response = client.post(
            "/api/agents/reviews", json={**_BODY, "research_run_id": env.run_id}, headers=_HEADERS
        )
    assert response.status_code == 409
    assert "no longer matches" in response.json()["detail"]


def test_second_button_press_is_refused_while_a_job_runs(env: Env) -> None:
    entered = threading.Event()
    release = threading.Event()

    class Slow(LocalProvider):
        def chat_json(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            entered.set()
            assert release.wait(timeout=8)
            return super().chat_json(*args, **kwargs)

    provider = Slow(happy_script(env))
    with _client(env, provider) as client:
        first = client.post(
            "/api/agents/reviews", json={**_BODY, "research_run_id": env.run_id}, headers=_HEADERS
        )
        assert first.status_code == 200, first.text
        assert entered.wait(timeout=8)
        second = client.post(
            "/api/agents/reviews", json={**_BODY, "research_run_id": env.run_id}, headers=_HEADERS
        )
        assert second.status_code == 409
        assert "already running" in second.json()["detail"]
        release.set()
        job = _wait_for_job(client, int(first.json()["job_id"]))
    assert job["status"] == "succeeded"


def test_only_one_job_at_a_time_and_restart_marks_it_interrupted(env: Env) -> None:
    store = AgentStore(env.agents)
    job = store.create_job(research_run_id=env.run_id, model="fake-model")
    with pytest.raises(AgentStoreError):
        store.create_job(research_run_id=env.run_id, model="fake-model")
    run = store.create_run(research_run_id=env.run_id, model="fake-model", fingerprint="f")
    store.mark_job_running(int(job["id"]))
    store.attach_job_run(int(job["id"]), int(run["id"]))
    store.start_stage(int(run["id"]), "researcher", "researcher")

    with TestClient(create_app(make_settings(env.tmp))) as client:
        after = client.get(f"/api/agents/jobs/{job['id']}").json()
        detail = client.get(f"/api/agents/runs/{run['id']}").json()
    assert after["status"] == "interrupted"
    assert detail["status"] == "failed"
    assert detail["error_code"] == "interrupted"
    assert detail["stages"][0]["status"] == "failed"
    assert Path(env.agents).exists()
