"""Read-only Alpaca headlines and an opt-in local interpretation."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlencode

from nomadquant.agents.ollama import OllamaError, OllamaProvider
from nomadquant.config import Settings
from nomadquant.news.store import NewsStore, headline_hash

_NEWS_URL = "https://data.alpaca.markets/v1beta1/news"
_STAGE_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
}
_ROLES = (
    (
        "researcher",
        "ROLE: Researcher. State only what this stored headline says. Do not invent prices.",
    ),
    (
        "skeptic",
        "ROLE: Skeptic. You receive the Researcher's notes. Challenge causal claims. "
        "Do not invent prices.",
    ),
    (
        "reviewer",
        "ROLE: Reviewer. You receive the Researcher and Skeptic notes. Say whether the "
        "headline is enough to change a price-only monthly momentum rule. It is not.",
    ),
)


SOURCE = "Alpaca News API (data.alpaca.markets)"


def news_view(settings: Settings) -> dict[str, Any]:
    store = NewsStore.open_readonly(settings.news_path)
    if store is None:
        return {
            "status": "not_loaded",
            "detail": "News has not been requested. Nothing is invented in its place.",
            "items": [],
            "fetches": [],
            "source": SOURCE,
            "live": False,
            "broker_orders": False,
        }
    meta = store.status()
    return {
        **meta,
        "items": store.articles(),
        "fetches": store.fetches(),
        "source": SOURCE,
        "live": False,
        "broker_orders": False,
        "note": "Headlines and links only. This is not a live quote and not a strategy change.",
    }


def refresh_news(settings: Settings, *, opener: Any | None = None) -> dict[str, Any]:
    """Explicit fetch. Does not run unless the user asks."""
    key = "" if settings.alpaca_api_key is None else settings.alpaca_api_key.get_secret_value()
    secret = (
        "" if settings.alpaca_api_secret is None else settings.alpaca_api_secret.get_secret_value()
    )
    store = NewsStore(settings.news_path)
    fetch_id = store.start_fetch(SOURCE)
    started = time.monotonic()

    def done(status: str, count: int, detail: str) -> None:
        store.finish_fetch(
            fetch_id,
            status=status,
            count=count,
            duration_ms=int((time.monotonic() - started) * 1000),
            detail=detail,
        )

    if not key or not secret:
        store.record_status("unavailable", "Alpaca credentials are not configured.")
        done("unavailable", 0, "Alpaca credentials are not configured.")
        return news_view(settings)
    query = urlencode({"symbols": "SPY,QQQ", "limit": 15})
    request = urllib.request.Request(
        f"{_NEWS_URL}?{query}",
        headers={
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
        },
        method="GET",
    )
    client = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with client.open(request, timeout=8) as response:
            payload = json.loads(response.read(1_000_000))
    except urllib.error.HTTPError as exc:
        detail = "News entitlement was refused." if exc.code in {401, 403} else f"HTTP {exc.code}"
        store.record_status("unavailable", detail)
        done("unavailable", 0, detail)
        return news_view(settings)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        store.record_status("unavailable", type(exc).__name__)
        done("unavailable", 0, type(exc).__name__)
        return news_view(settings)
    articles = _articles(payload)
    store.replace_articles(articles, status="ok", detail=f"{len(articles)} headlines stored.")
    done("ok", len(articles), f"{len(articles)} headlines stored.")
    return news_view(settings)


def analyze_headline(
    settings: Settings,
    article_id: str,
    *,
    provider: OllamaProvider | None = None,
) -> dict[str, Any]:
    """Sequential Researcher → Skeptic → Reviewer reading. Not a strategy change."""
    store = NewsStore(settings.news_path)
    article = store.article(article_id)
    if article is None:
        raise ValueError("That headline is not in the local store.")
    review_id = store.add_review(article_id)
    local = provider or OllamaProvider(settings.ollama_base_url)
    health = local.health(timeout=2.0)
    model = ""
    installed = [str(item) for item in health.get("models") or []]
    for name in (settings.ollama_model, "qwen3.5:9b", "gemma4:12b"):
        if name and name in installed:
            model = name
            break
    headline = str(article["headline"])
    source = str(article["source"])
    context = {
        "headline": headline,
        "source": source,
        "published_at": str(article.get("published_at") or ""),
        "url": str(article.get("url") or ""),
    }
    notes: dict[str, str] = {}
    if not model:
        report = {
            "researcher": f"Stored headline from {source}: {headline}",
            "skeptic": "No local model is available, so no interpretation was added.",
            "reviewer": "Insufficient evidence for a market conclusion.",
            "verification": "numbers_not_added",
            "label": "interpretation_not_a_strategy_change",
        }
        store.finish_review(review_id, status="offline", model="", report=report)
        return _view(store, review_id)
    for name, instruction in _ROLES:
        stage_id = store.start_stage(review_id, name, model=model, payload={**context, **notes})
        user = f"Source: {source}\nHeadline: {headline}\nPublished: {context['published_at']}\n" + (
            "" if not notes else "Prior notes:\n" + json.dumps(notes)
        )
        try:
            parsed = local.chat_json(
                model,
                [
                    {
                        "role": "system",
                        "content": (
                            "Read only the stored headline and the prior notes. "
                            f'{instruction} Reply with JSON {{"text": "..."}}. '
                            "Do not invent prices. This cannot change the registered strategy."
                        ),
                    },
                    {"role": "user", "content": user},
                ],
                _STAGE_SCHEMA,
                timeout=25,
                num_ctx=4096,
            )
        except OllamaError as exc:
            store.finish_stage(stage_id, status="failed", output={}, error_safe=type(exc).__name__)
            store.finish_review(
                review_id,
                status="failed",
                model=model,
                report={"error": type(exc).__name__, "failed_stage": name},
            )
            return _view(store, review_id)
        text = str(parsed.get("text") or "").strip()
        notes[name] = text
        store.finish_stage(stage_id, status="succeeded", output={"text": text})
    verification_id = store.start_stage(
        review_id, "verifier", model="", payload={"headline": headline, **notes}
    )
    blob = " ".join(notes.values())
    if _invented_number(blob, headline):
        notes = {
            "researcher": f"Stored headline from {source}: {headline}",
            "skeptic": (
                "The model added a figure that is not in the headline. That text was discarded."
            ),
            "reviewer": "Insufficient evidence.",
        }
        verdict = "rejected_unsupported_number"
        store.finish_stage(verification_id, status="failed", output={"verification": verdict})
        status = "completed"
    else:
        verdict = "headline_only"
        store.finish_stage(verification_id, status="succeeded", output={"verification": verdict})
        status = "completed"
    finished: dict[str, Any] = {
        **notes,
        "verification": verdict,
        "label": "interpretation_not_a_strategy_change",
        "strategy_override": False,
    }
    store.finish_review(review_id, status=status, model=model, report=finished)
    return _view(store, review_id)


def _view(store: NewsStore, review_id: int) -> dict[str, Any]:
    viewed = store.review(review_id)
    assert viewed is not None
    viewed["broker_orders"] = False
    viewed["strategy_override"] = False
    return viewed


def _articles(payload: object) -> list[dict[str, str]]:
    rows = payload.get("news") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    articles: list[dict[str, str]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        headline = str(item.get("headline") or "").strip()
        article_id = str(item.get("id") or "")
        if not headline or not article_id:
            continue
        symbols = item.get("symbols")
        if not isinstance(symbols, list):
            symbols = []
        published = str(item.get("created_at") or "")
        articles.append(
            {
                "id": article_id,
                "headline": headline[:300],
                "source": str(item.get("source") or "unknown")[:120],
                "url": str(item.get("url") or "")[:500],
                "published_at": published,
                "updated_at": str(item.get("updated_at") or published),
                "symbols": ",".join(str(symbol) for symbol in symbols[:12]),
                "content_hash": headline_hash(headline, published),
            }
        )
    return articles


def _invented_number(text: str, headline: str) -> bool:
    import re

    for token in re.findall(r"\d[\d,]*(?:\.\d+)?%?", text):
        plain = token.replace(",", "")
        if plain in {"0", "1"}:
            continue
        if token not in headline and plain not in headline:
            return True
    return False
