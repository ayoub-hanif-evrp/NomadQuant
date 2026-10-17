"""Read-only Alpaca headlines and an opt-in local interpretation."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlencode

from nomadquant.agents.ollama import OllamaError, OllamaProvider
from nomadquant.config import Settings
from nomadquant.news.store import NewsStore, headline_hash

_NEWS_URL = "https://data.alpaca.markets/v1beta1/news"
_SCHEMA = {
    "type": "object",
    "properties": {
        "researcher": {"type": "string"},
        "skeptic": {"type": "string"},
        "reviewer": {"type": "string"},
    },
    "required": ["researcher", "skeptic", "reviewer"],
}


def news_view(settings: Settings) -> dict[str, Any]:
    store = NewsStore.open_readonly(settings.news_path)
    if store is None:
        return {
            "status": "not_loaded",
            "detail": "News has not been requested. Nothing is invented in its place.",
            "items": [],
            "live": False,
            "broker_orders": False,
        }
    meta = store.status()
    return {
        **meta,
        "items": store.articles(),
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
    if not key or not secret:
        store.record_status("unavailable", "Alpaca credentials are not configured.")
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
        return news_view(settings)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        store.record_status("unavailable", type(exc).__name__)
        return news_view(settings)
    articles = _articles(payload)
    store.replace_articles(articles, status="ok", detail=f"{len(articles)} headlines stored.")
    return news_view(settings)


def analyze_headline(
    settings: Settings,
    article_id: str,
    *,
    provider: OllamaProvider | None = None,
) -> dict[str, Any]:
    """One opt-in local reading of a stored headline. Not a strategy change."""
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
    if not model:
        report = {
            "researcher": f"Stored headline from {source}: {headline}",
            "skeptic": "No local model is available, so no interpretation was added.",
            "reviewer": "Insufficient evidence for a market conclusion.",
            "verification": "numbers_not_added",
        }
        store.finish_review(review_id, status="offline", model="", report=report)
        viewed = store.review(review_id)
        assert viewed is not None
        viewed["broker_orders"] = False
        return viewed
    try:
        parsed = local.chat_json(
            model,
            [
                {
                    "role": "system",
                    "content": (
                        "Read only the headline. Researcher states what it says. "
                        "Skeptic challenges any causal claim. Reviewer says whether it is "
                        "enough to change a price-only momentum rule. Do not invent prices."
                    ),
                },
                {"role": "user", "content": f"Source: {source}\nHeadline: {headline}"},
            ],
            _SCHEMA,
            timeout=25,
            num_ctx=4096,
        )
    except OllamaError as exc:
        store.finish_review(
            review_id,
            status="failed",
            model=model,
            report={"error": type(exc).__name__},
        )
        viewed = store.review(review_id)
        assert viewed is not None
        viewed["broker_orders"] = False
        return viewed
    report = {
        "researcher": str(parsed.get("researcher") or ""),
        "skeptic": str(parsed.get("skeptic") or ""),
        "reviewer": str(parsed.get("reviewer") or ""),
        "verification": "headline_only",
        "label": "interpretation_not_a_strategy_change",
    }
    blob = " ".join(report[key] for key in ("researcher", "skeptic", "reviewer"))
    if _invented_number(blob, headline):
        report = {
            "researcher": f"Stored headline from {source}: {headline}",
            "skeptic": (
                "The model added a figure that is not in the headline. That text was discarded."
            ),
            "reviewer": "Insufficient evidence.",
            "verification": "rejected_unsupported_number",
        }
    store.finish_review(review_id, status="completed", model=model, report=report)
    viewed = store.review(review_id)
    assert viewed is not None
    viewed["broker_orders"] = False
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
