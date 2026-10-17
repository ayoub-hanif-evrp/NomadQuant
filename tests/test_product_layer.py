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


_NO_QUOTES: dict[str, object] = {"status": "unavailable", "detail": "test", "quotes": {}}


def test_copilot_answers_from_stored_cash_without_a_model(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    result = answer_question(
        settings,
        "How much virtual money do I currently have?",
        provider=_Offline(),  # type: ignore[arg-type]
        quotes=_NO_QUOTES,
    )
    assert result["broker_orders"] is False
    assert result["mode"] == "stored_records"
    assert "100" in result["answer"]
    assert result["evidence_ids"] == ["portfolio"]
    assert result["follow_ups"]


def test_copilot_explains_why_there_is_no_trade(tmp_path: Path) -> None:
    result = answer_question(
        make_settings(tmp_path),
        "Why didn't the system buy SPY?",
        provider=_Offline(),  # type: ignore[arg-type]
        quotes=_NO_QUOTES,
    )
    assert "trading.reasons" in result["evidence_ids"]
    assert "first trading day of a month" in result["answer"]


def test_copilot_keeps_a_grounded_model_answer_and_history(tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    class _Grounded:
        def health(self, timeout: float = 2.0) -> dict[str, object]:
            return {"available": True, "models": ["qwen3.5:9b"]}

        def chat_json(self, _model: str, messages: list[dict[str, str]], *_a: object, **_k: object):
            seen["messages"] = messages
            return {
                "answer": "Your internal book holds 100 USD in cash.",
                "used_evidence_ids": ["portfolio"],
                "follow_ups": ["Why are there no trades yet?"],
            }

    settings = make_settings(tmp_path)
    settings.ollama_model = "qwen3.5:9b"
    result = answer_question(
        settings,
        "And how much cash?",
        history=[{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi"}],
        provider=_Grounded(),  # type: ignore[arg-type]
        quotes=_NO_QUOTES,
    )
    assert result["mode"] == "local_model"
    assert result["follow_ups"] == ["Why are there no trades yet?"]
    roles = [item["role"] for item in seen["messages"]]  # type: ignore[union-attr]
    assert roles == ["system", "user", "assistant", "user"]


def test_live_quote_is_display_only_and_skips_network_without_keys(tmp_path: Path) -> None:
    from nomadquant.marketdata.live_quote import clear_cache, live_quotes

    clear_cache()
    body = live_quotes(make_settings(tmp_path))
    clear_cache()
    assert body["status"] == "unavailable"
    assert body["used_by_strategy"] is False
    assert body["feed"] == "iex"


def test_live_quote_parses_an_iex_snapshot(tmp_path: Path) -> None:
    import io

    from pydantic import SecretStr

    from nomadquant.marketdata.live_quote import clear_cache, live_quotes

    snapshot = {
        "SPY": {
            "latestTrade": {"p": 763.31, "t": "2026-10-16T20:47:54Z"},
            "dailyBar": {
                "o": 760.0,
                "h": 765.0,
                "l": 758.0,
                "c": 763.0,
                "v": 10,
                "t": "2026-10-16",
            },
            "prevDailyBar": {"c": 760.0},
        }
    }

    class _Opener:
        def open(self, request: object, timeout: float) -> io.BytesIO:
            assert "feed=iex" in request.full_url  # type: ignore[attr-defined]
            return io.BytesIO(json.dumps(snapshot).encode())

    settings = make_settings(tmp_path)
    settings.alpaca_api_key = SecretStr("key")
    settings.alpaca_api_secret = SecretStr("secret")
    clear_cache()
    body = live_quotes(settings, opener=_Opener())
    clear_cache()
    assert body["status"] == "ok"
    assert body["quotes"]["SPY"]["price"] == 763.31
    assert body["quotes"]["SPY"]["change"] == 3.31


def test_overview_explains_trading_state_from_records(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from nomadquant.overview import next_rebalance, overview

    view = overview(make_settings(tmp_path), now=datetime(2026, 10, 17, 12, 0, tzinfo=UTC))
    assert view["clock"]["weekday"] == "Saturday"
    assert view["clock"]["state"] == "closed"
    assert view["clock"]["next_open"].startswith("2026-10-19T09:30")
    assert view["trading"]["next_rebalance"] == {
        "signal_session": "2026-11-02",
        "fill_session": "2026-11-03",
    }
    assert view["broker_orders"] is False
    from datetime import date

    assert next_rebalance(date(2026, 10, 1))["signal_session"] == "2026-10-01"


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
    fetches = response.json()["fetches"]
    assert fetches[0]["status"] == "unavailable"
    assert fetches[0]["finished_at"]


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
        quotes=_NO_QUOTES,
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
