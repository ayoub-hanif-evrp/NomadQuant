"""Copilot, news, and explicit mutations stay read-only until confirmed."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from nomadquant.api.app import create_app
from nomadquant.copilot.service import answer_question
from tests.conftest import make_settings

_HEADERS = {"Origin": "http://127.0.0.1:3000", "X-NomadQuant-Intent": "mutate"}


class _Offline:
    def health(self, timeout: float = 2.0) -> dict[str, object]:
        return {"available": False, "models": []}


def test_copilot_answers_from_stored_cash_without_a_model(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    result = answer_question(
        settings,
        "How much virtual money do I currently have?",
        provider=_Offline(),  # type: ignore[arg-type]
    )
    assert result["broker_orders"] is False
    assert result["mode"] == "stored_records"
    assert "100" in result["answer"] or "unavailable" in result["answer"]
    assert result["evidence_ids"]


def test_copilot_post_requires_the_local_header(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        blocked = client.post("/api/copilot/ask", json={"question": "Is the data current?"})
    assert blocked.status_code == 403


def test_news_get_does_not_create_a_database_or_invent_articles(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/api/news/headlines")
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["status"] == "not_loaded"
    assert not Path(settings.news_path).exists()


def test_news_refresh_without_credentials_does_not_call_the_network(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post("/api/news/refresh", headers=_HEADERS)
    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert response.json()["items"] == []


def test_sync_requires_phrase_and_does_not_download_without_it(
    tmp_path: Path, monkeypatch: object
) -> None:
    called = {"n": 0}

    def _sync(*_args: object, **_kwargs: object) -> dict[str, object]:
        called["n"] += 1
        return {"sync": "noop", "broker_orders": False}

    monkeypatch.setattr("nomadquant.shadow.data_ops.data_sync", _sync)  # type: ignore[attr-defined]
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        missing = client.post(
            "/api/market-data/sync",
            json={"confirm": "SYNC_HISTORICAL_BARS"},
        )
        wrong = client.post(
            "/api/market-data/sync",
            json={"confirm": "nope"},
            headers=_HEADERS,
        )
        accepted = client.post(
            "/api/market-data/sync",
            json={"confirm": "SYNC_HISTORICAL_BARS"},
            headers=_HEADERS,
        )
    assert missing.status_code == 403
    assert wrong.status_code == 409
    assert accepted.status_code == 200
    assert called["n"] == 1


def test_review_start_refuses_an_uninstalled_model(tmp_path: Path, monkeypatch: object) -> None:
    class _Provider:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def health(self, timeout: float = 2.0) -> dict[str, object]:
            return {"available": True, "models": ["qwen3.5:9b"]}

    monkeypatch.setattr("nomadquant.api.agent_routes.OllamaProvider", _Provider)
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        response = client.post(
            "/api/agents/reviews",
            json={
                "research_run_id": 2,
                "model": "missing-model",
                "confirm": "RUN_LOCAL_RESEARCH_REVIEW",
            },
            headers=_HEADERS,
        )
    assert response.status_code == 409
    assert "not installed" in response.json()["detail"]


def test_headline_number_guard_discards_invented_figures() -> None:
    from nomadquant.news.service import _invented_number

    assert _invented_number("SPY fell 4.2%", "Fed holds rates")
    assert not _invented_number("The headline mentions no figure.", "Fed holds rates")


def test_model_answer_with_an_extra_price_is_discarded(tmp_path: Path) -> None:
    class _Talkative:
        def health(self, timeout: float = 2.0) -> dict[str, object]:
            return {"available": True, "models": ["qwen3.5:9b"]}

        def chat_json(self, *_args: object, **_kwargs: object) -> dict[str, object]:
            return {
                "answer": "SPY is at 999.99 today.",
                "used_evidence_ids": ["market.spy"],
            }

    settings = make_settings(tmp_path)
    settings.ollama_model = "qwen3.5:9b"
    result = answer_question(
        settings,
        "What is the latest SPY price?",
        provider=_Talkative(),  # type: ignore[arg-type]
    )
    assert "999.99" not in result["answer"]
    assert result["mode"] == "stored_records"


def test_news_payload_keeps_headline_not_article_body() -> None:
    from nomadquant.news.service import _articles

    articles = _articles(
        {
            "news": [
                {
                    "id": "1",
                    "headline": "Index fund sees inflows",
                    "source": "Example",
                    "url": "https://example.test/story",
                    "created_at": "2026-10-16T12:00:00Z",
                    "symbols": ["SPY"],
                    "summary": "A long copyrighted article body that must not be stored.",
                }
            ]
        }
    )
    encoded = json.dumps(articles)
    assert "Index fund sees inflows" in encoded
    assert "copyrighted" not in encoded
