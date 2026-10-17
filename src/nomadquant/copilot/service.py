"""Grounded answers from local records. The model cannot invent figures."""

from __future__ import annotations

import re
from typing import Any

from nomadquant.agents.ollama import OllamaError, OllamaProvider
from nomadquant.config import Settings
from nomadquant.marketdata.availability import latest_safe_session
from nomadquant.shadow.data_ops import data_check
from nomadquant.shadow.pilot import supervised_readiness

_PREFERRED = ("qwen3.5:9b", "gemma4:12b")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?%?")
_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "used_evidence_ids": {"type": "array"},
    },
    "required": ["answer", "used_evidence_ids"],
}


def collect_evidence(settings: Settings) -> list[dict[str, str]]:
    """Read-only facts. No secrets and no broker orders."""
    from datetime import UTC, datetime

    facts: list[dict[str, str]] = []
    now = datetime.now(UTC)
    try:
        eligible = latest_safe_session(now, "sip").isoformat()
    except Exception:  # noqa: BLE001 - freshness must still answer
        eligible = "unknown"
    coverage = data_check(settings, feed="sip")
    spy = (coverage.get("symbols") or {}).get("SPY") or {}
    latest = spy.get("latest_stored") or "none"
    facts.append(
        {
            "id": "market.spy",
            "source": "local SIP daily store",
            "text": (
                f"SPY SIP daily bars are historical, not a live quote. "
                f"Latest stored session {latest}. Latest eligible completed session {eligible}. "
                f"Missing sessions in the strategy window: "
                f"{coverage.get('missing_count', 'unknown')}."
            ),
        }
    )
    readiness = supervised_readiness(settings)
    facts.append(
        {
            "id": "pilot.state",
            "source": "shadow pilot readiness",
            "text": (
                f"Forward pilot state is {readiness.get('state')}. "
                f"Cash in the internal shadow book is "
                f"{readiness.get('cash_usd') or 'unavailable'}. "
                "This is not an Alpaca order and not broker equity."
            ),
        }
    )
    facts.append(
        {
            "id": "scope.locks",
            "source": "configuration locks",
            "text": (
                "Trading mode is paper. Order submission is disabled. "
                "The internal virtual capital is 100 USD. "
                "A historical backtest is not the forward shadow book."
            ),
        }
    )
    _agent_fact(settings, facts)
    return facts


def answer_question(
    settings: Settings,
    question: str,
    *,
    provider: OllamaProvider | None = None,
) -> dict[str, Any]:
    text = " ".join(question.split())
    if not text:
        raise ValueError("A question is required.")
    if len(text) > 500:
        raise ValueError("Ask a shorter question.")
    evidence = collect_evidence(settings)
    grounded = _deterministic(text, evidence)
    model_name = ""
    mode = "stored_records"
    answer = grounded["answer"]
    used = grounded["evidence_ids"]
    note = "Answered from stored records without a model."
    local = provider
    installed: list[str] = []
    if local is None:
        local = OllamaProvider(settings.ollama_base_url)
    health = local.health(timeout=2.0)
    if health.get("available"):
        installed = [str(item) for item in health.get("models") or []]
        model_name = _choose_model(settings, installed)
    if model_name:
        drafted = _ask_model(local, model_name, text, evidence)
        if drafted is not None:
            answer = drafted["answer"]
            used = drafted["evidence_ids"]
            mode = "local_model"
            note = "The model could only use the evidence ids listed here."
    return {
        "answer": answer,
        "evidence": [item for item in evidence if item["id"] in used],
        "evidence_ids": used,
        "mode": mode,
        "model": model_name or None,
        "ollama_available": bool(health.get("available")),
        "installed_models": installed,
        "broker_orders": False,
        "note": note,
    }


def _agent_fact(settings: Settings, facts: list[dict[str, str]]) -> None:
    from pathlib import Path

    from nomadquant.agents.store import AgentStore

    path = Path(settings.agents_path)
    if not path.is_file():
        facts.append(
            {
                "id": "agent.latest",
                "source": "agent runs",
                "text": "No agent review is stored. Agents are idle.",
            }
        )
        return
    store = AgentStore(path)
    runs = store.list_runs(limit=1, offset=0)
    if not runs:
        facts.append(
            {
                "id": "agent.latest",
                "source": "agent runs",
                "text": "No agent review is stored. Agents are idle.",
            }
        )
        return
    run = runs[0]
    facts.append(
        {
            "id": f"agent.run.{run['id']}",
            "source": "agent run",
            "text": (
                f"Latest stored agent run {run['id']} is a {run.get('label') or 'review'} "
                f"with status {run.get('status')} and verdict {run.get('verdict') or 'none'}. "
                "It reviews stored research. It is not a live trading decision."
            ),
        }
    )


def _deterministic(question: str, evidence: list[dict[str, str]]) -> dict[str, Any]:
    by_id = {item["id"]: item["text"] for item in evidence}
    folded = question.lower()
    chosen: list[str] = []
    if any(word in folded for word in ("cash", "money", "portfolio", "worth", "virtual")):
        chosen.append("pilot.state")
    if any(word in folded for word in ("price", "fresh", "current", "spy", "market", "quote")):
        chosen.append("market.spy")
    if any(word in folded for word in ("skeptic", "agent", "researcher", "review")):
        chosen.extend(item["id"] for item in evidence if item["id"].startswith("agent."))
    if any(word in folded for word in ("buy", "sell", "approv", "decision", "trade")):
        chosen.extend(["pilot.state", "scope.locks"])
    if any(word in folded for word in ("backtest", "2019", "historical", "real trading")):
        chosen.append("scope.locks")
    if not chosen:
        chosen = [item["id"] for item in evidence[:3]]
    unique = list(dict.fromkeys(chosen))
    sentences = [by_id[item] for item in unique if item in by_id]
    return {"answer": " ".join(sentences), "evidence_ids": unique}


def _choose_model(settings: Settings, installed: list[str]) -> str:
    if settings.ollama_model and settings.ollama_model in installed:
        return settings.ollama_model
    for name in _PREFERRED:
        if name in installed:
            return name
    return ""


def _ask_model(
    provider: OllamaProvider,
    model: str,
    question: str,
    evidence: list[dict[str, str]],
) -> dict[str, Any] | None:
    packet = "\n".join(f"{item['id']}: {item['text']}" for item in evidence)
    messages = [
        {
            "role": "system",
            "content": (
                "Explain only the evidence lines. Do not add prices, dates, quantities, "
                "or performance figures that are not written in those lines. "
                "If the evidence is insufficient, say so."
            ),
        },
        {"role": "user", "content": f"Evidence:\n{packet}\n\nQuestion: {question}"},
    ]
    try:
        parsed = provider.chat_json(model, messages, _SCHEMA, timeout=25, num_ctx=4096)
    except OllamaError:
        return None
    answer = str(parsed.get("answer") or "").strip()
    raw_ids = parsed.get("used_evidence_ids")
    if not answer or not isinstance(raw_ids, list):
        return None
    known = {item["id"] for item in evidence}
    used = [str(item) for item in raw_ids if str(item) in known]
    if not used:
        return None
    allowed = "\n".join(item["text"] for item in evidence if item["id"] in used)
    if _unsupported_numbers(answer, allowed):
        return None
    return {"answer": answer, "evidence_ids": used}


def _unsupported_numbers(answer: str, evidence: str) -> list[str]:
    bad: list[str] = []
    for token in _NUMBER.findall(answer):
        plain = token.replace(",", "")
        if plain in {"0", "1"}:
            continue
        if token not in evidence and plain not in evidence:
            bad.append(token)
    return bad
