"""Server-side event search and histogram."""

from pathlib import Path

from fastapi.testclient import TestClient

from nomadquant.api.app import create_app
from nomadquant.audit import AuditLog
from tests.conftest import make_settings


def _seed(path: Path) -> AuditLog:
    audit = AuditLog(path, [])
    audit.record_event(
        event_type="market_data.sync",
        event_level="info",
        component="market_data",
        status="succeeded",
        title="SIP sync complete",
        summary="Fetched SPY and QQQ daily bars.",
    )
    audit.record_event(
        event_type="research.run",
        event_level="warning",
        component="research",
        status="warning",
        title="Replay note",
        summary="Fingerprint matched with caveats.",
    )
    audit.record_event(
        event_type="api.error",
        event_level="error",
        component="system",
        status="failed",
        title="Request failed",
        summary="An API request failed.",
    )
    return audit


def test_events_q_searches_title_and_summary(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    _seed(Path(settings.database_path))
    with TestClient(create_app(settings)) as client:
        spy = client.get("/api/observability/events", params={"q": "SPY"}).json()
        replay = client.get("/api/observability/events", params={"q": "Replay"}).json()
        missing = client.get("/api/observability/events", params={"q": "order-submit"}).json()
    assert spy["total"] == 1
    assert spy["items"][0]["title"] == "SIP sync complete"
    assert replay["total"] == 1
    assert missing["total"] == 0


def test_events_histogram_buckets_by_day(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    _seed(Path(settings.database_path))
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/observability/events/histogram", params={"bucket": "day"})
        bad = client.get("/api/observability/events/histogram", params={"bucket": "week"})
    assert response.status_code == 200
    body = response.json()
    assert body["bucket"] == "day"
    assert len(body["buckets"]) >= 1
    # Startup event from create_app lifespan is also counted.
    total = sum(item["count"] for item in body["buckets"])
    assert total >= 3
    errors = sum(item["errors"] for item in body["buckets"])
    warnings = sum(item["warnings"] for item in body["buckets"])
    assert errors == 1
    assert warnings == 1
    assert bad.status_code == 400


def test_histogram_path_is_not_captured_as_event_id(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/observability/events/histogram")
    assert response.status_code == 200
    assert "buckets" in response.json()
