"""Grounded answers from local records. The model cannot invent figures."""

from __future__ import annotations

import re
from typing import Any

from nomadquant.agents.ollama import OllamaError, OllamaProvider
from nomadquant.config import Settings

_PREFERRED = ("qwen3.5:9b", "gemma4:12b")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?%?")
_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "used_evidence_ids": {"type": "array"},
        "follow_ups": {"type": "array"},
    },
    "required": ["answer", "used_evidence_ids"],
}
_SYSTEM = (
    "You are Nomad Copilot inside NomadQuant, a local research workstation that simulates a "
    "$100 SPY strategy. Talk to the user like a calm, friendly analyst. Answer the question "
    "directly in 2 to 5 short sentences of plain English, then add one practical next step if "
    "it helps. Use only the evidence lines. Every price, date, amount, or count you write must "
    "appear in those lines. If the evidence does not answer the question, say what is missing. "
    "When asked why something has not happened, name every reason marked 'Not yet' and say "
    "when the next chance is. "
    "Agent reviews look at past research. They never cause or block a trade. Never suggest "
    "placing a real order. Return JSON with answer, used_evidence_ids, and up to 3 short "
    "follow_ups the user could ask next."
)
_HISTORY_TURNS = 6


def collect_evidence(
    settings: Settings, *, quotes: dict[str, Any] | None = None
) -> list[dict[str, str]]:
    """Read-only facts. No secrets and no broker orders."""
    from nomadquant.overview import overview

    view = overview(settings)
    clock = view["clock"]
    data = view["data"]
    trading = view["trading"]
    portfolio = view["portfolio"]
    facts: list[dict[str, str]] = [
        {
            "id": "clock",
            "source": "NYSE calendar",
            "text": (
                f"Today is {clock['weekday']} {clock['today']} in New York. {clock['label']}. "
                f"Next market open: {clock['next_open'][:16].replace('T', ' ')} New York time. "
                f"Last finished trading day: {clock['last_completed_session']}."
            ),
        },
        {
            "id": "data.sip",
            "source": "local SIP daily store",
            "text": (
                f"Strategy data is SIP daily bars. Latest stored day {data['latest_stored']}. "
                f"Latest finished day available {data['latest_eligible']}. "
                + (
                    "The stored data is current."
                    if data["current"]
                    else "The stored data is behind. Missing days: "
                    + ", ".join(data["missing_sessions"] or ["unknown"])
                    + ". The user can press Update data to download them."
                )
            ),
        },
        {
            "id": "trading.status",
            "source": "forward pilot",
            "text": (
                f"{trading['headline']}. {trading['summary']} "
                f"Lifecycle {trading.get('lifecycle') or trading.get('state')}. "
                f"Pilot clock "
                + (
                    "is set."
                    if trading.get("pilot_clock_started")
                    else "is not set. The user can arm it without waiting for month-start."
                )
            ),
        },
        {
            "id": "trading.reasons",
            "source": "forward pilot readiness",
            "text": " ".join(
                f"{'OK' if check['ok'] else 'Not yet'}: {check['title']}. {check['detail']}"
                for check in trading["checks"]
            ),
        },
        {
            "id": "trading.history",
            "source": "forward shadow cycles",
            "text": (
                "Recent daily checks: "
                + (
                    "; ".join(
                        f"{item['session']} {item['result']}"
                        for item in trading["recent_decisions"]
                    )
                    or "none recorded"
                )
                + f". Simulated fills so far: {trading['simulated_fills']}."
            ),
        },
        {
            "id": "portfolio",
            "source": "internal shadow ledger",
            "text": (
                f"The internal book started with {portfolio['starting_usd']} USD. "
                f"Equity {portfolio['equity_usd']} USD, cash {portfolio['cash_usd']} USD, "
                f"holdings {_holdings(portfolio['holdings'])}. "
                "This is simulated money, not an Alpaca balance."
            ),
        },
        {
            "id": "strategy",
            "source": "registered strategy spy_tsmom_12_1",
            "text": view["strategy"]["plain"],
        },
        {
            "id": "scope.locks",
            "source": "configuration locks",
            "text": (
                "Trading mode is paper. Sending orders to Alpaca is switched off. "
                "A historical backtest is research, not the forward $100 book."
            ),
        },
    ]
    facts.append(_live_fact(settings, quotes))
    facts.append(_news_fact(settings))
    facts.append(_agent_fact(settings))
    facts.append(_lab_fact(settings))
    return facts


def answer_question(
    settings: Settings,
    question: str,
    *,
    history: list[dict[str, str]] | None = None,
    provider: OllamaProvider | None = None,
    quotes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = " ".join(question.split())
    if not text:
        raise ValueError("A question is required.")
    if len(text) > 500:
        raise ValueError("Ask a shorter question.")
    evidence = collect_evidence(settings, quotes=quotes)
    grounded = _deterministic(text, evidence)
    model_name = ""
    mode = "stored_records"
    answer = grounded["answer"]
    used = grounded["evidence_ids"]
    follow_ups = grounded["follow_ups"]
    note = "Answered from stored records without a model."
    local = provider
    installed: list[str] = []
    if local is None:
        local = OllamaProvider(settings.ollama_base_url)
    health = local.health(timeout=2.0)
    if health.get("available"):
        installed = [str(item) for item in health.get("models") or []]
        model_name = _choose_model(settings, installed)
    if model_name and "lab" not in grounded["evidence_ids"]:
        drafted = _ask_model(local, model_name, text, evidence, history or [])
        if drafted is not None:
            answer = drafted["answer"]
            used = drafted["evidence_ids"]
            follow_ups = drafted["follow_ups"] or follow_ups
            mode = "local_model"
            note = "Written by the local model from the evidence cards below."
        else:
            note = "The model reply was not used because it was unsupported or late."
    elif model_name:
        note = "The stored Simulation Lab record was kept. A model rewrite was not used."
    return {
        "answer": answer,
        "evidence": [item for item in evidence if item["id"] in used],
        "evidence_ids": used,
        "follow_ups": follow_ups[:3],
        "mode": mode,
        "model": model_name or None,
        "ollama_available": bool(health.get("available")),
        "installed_models": installed,
        "broker_orders": False,
        "note": note,
    }


def _holdings(holdings: object) -> str:
    if not isinstance(holdings, dict) or not holdings:
        return "none, all cash"
    return ", ".join(f"{symbol} {quantity}" for symbol, quantity in holdings.items())


def _live_fact(settings: Settings, quotes: dict[str, Any] | None) -> dict[str, str]:
    if quotes is None:
        from nomadquant.marketdata.live_quote import live_quotes

        quotes = live_quotes(settings)
    spy = (quotes.get("quotes") or {}).get("SPY") if quotes.get("status") == "ok" else None
    if not spy:
        return {
            "id": "live.iex",
            "source": "Alpaca IEX snapshot",
            "text": "No real-time price is available right now. " + str(quotes.get("detail") or ""),
        }
    change = spy.get("change_pct")
    return {
        "id": "live.iex",
        "source": "Alpaca IEX snapshot",
        "text": (
            f"SPY last IEX trade was {spy['price']} USD at "
            f"{spy['trade_time'][:16].replace('T', ' ')} UTC"
            + (
                ". The regular US cash session is closed, so this is not a live 'right now' price."
                if spy.get("stale")
                else "."
            )
            + f" Previous close {spy.get('previous_close')} USD"
            + ("" if change is None else f", change {change}%")
            + ". This IEX price is display only. The strategy uses SIP daily bars."
        ),
    }


def _news_fact(settings: Settings) -> dict[str, str]:
    from nomadquant.news.service import news_view

    view = news_view(settings)
    items = view.get("items") or []
    if not items:
        return {
            "id": "news",
            "source": "Alpaca News API",
            "text": "No headlines are stored. The News Scout fetches them when the user presses "
            "Fetch news.",
        }
    top = "; ".join(f"{item['headline']} ({item['source']})" for item in items[:4])
    return {
        "id": "news",
        "source": "Alpaca News API",
        "text": f"Latest stored headlines: {top}. Headlines are not used by the strategy.",
    }


def _agent_fact(settings: Settings) -> dict[str, str]:
    from pathlib import Path

    from nomadquant.agents.store import AgentStore

    path = Path(settings.agents_path)
    runs = AgentStore(path).list_runs(limit=1, offset=0) if path.is_file() else []
    if not runs:
        return {
            "id": "agents",
            "source": "agent runs",
            "text": "No agent review is stored. The agents are idle.",
        }
    run = runs[0]
    return {
        "id": "agents",
        "source": f"agent run {run['id']}",
        "text": (
            f"The latest agent review, run {run['id']}, checked a past backtest. Status "
            f"{run.get('status')}, verdict {run.get('verdict') or 'none'}. It is research, "
            "not a trading decision."
        ),
    }


_TOPICS: tuple[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("buy", "sell", "trade", "trades", "trading", "working", "nothing", "bought"),
        ("trading.status", "trading.reasons"),
        ("When is the next possible trade?", "How does the strategy decide?"),
    ),
    (
        ("cash", "money", "portfolio", "worth", "virtual", "balance", "equity"),
        ("portfolio",),
        ("Why are there no trades yet?", "Is this real money?"),
    ),
    (
        ("price", "fresh", "current", "up to date", "date", "old", "real time", "realtime"),
        ("live.iex", "data.sip", "clock"),
        ("Why is the stored data behind?", "Is the market open?"),
    ),
    (
        ("open", "closed", "today", "time", "weekend"),
        ("clock",),
        ("What is SPY trading at?", "When is the next rebalance?"),
    ),
    (
        ("news", "headline"),
        ("news",),
        ("Does news change the strategy?", "What are the agents doing?"),
    ),
    (
        ("agent", "skeptic", "researcher", "reviewer", "crew"),
        ("agents",),
        ("What did the agents find?", "Why are there no trades yet?"),
    ),
    (
        ("pilot", "armed", "approval", "approve"),
        ("trading.status", "trading.reasons"),
        ("Is the pilot armed?", "Is approval needed?"),
    ),
    (
        ("strategy", "decide", "explain", "momentum", "rebalance", "next"),
        ("strategy", "trading.reasons"),
        ("Why are there no trades yet?", "How much virtual money do I have?"),
    ),
    (
        ("backtest", "2019", "historical", "real trading", "alpaca", "order"),
        ("scope.locks", "lab"),
        ("How does the strategy decide?", "Why are there no trades yet?"),
    ),
    (
        (
            "simulation",
            "replay",
            "drawdown",
            "cost",
            "costs",
            "rejected",
            "lab",
            "buy",
            "sell",
            "risk",
        ),
        ("lab", "scope.locks"),
        ("Why did the strategy buy?", "Is this forward profit?"),
    ),
)


def _lab_fact(settings: Settings) -> dict[str, str]:
    from nomadquant.lab.runner import latest_session

    session = latest_session(settings)
    if not session:
        return {
            "id": "lab",
            "source": "simulation lab",
            "text": (
                "No Simulation Lab session is stored. A lab run is an isolated historical "
                "replay or a synthetic mechanics test. It is not the forward $100 book."
            ),
        }
    comparisons = session.get("comparisons") or {}
    approval = session.get("approval") or {}
    requests = approval.get("requests") or []
    decisions = "; ".join(
        f"{item.get('action')} {item.get('result')}" for item in requests if isinstance(item, dict)
    )
    buys = [
        (
            f"On {item.get('session')} momentum {item.get('momentum')} "
            f"and risk {item.get('risk_verdict')} recorded a buy."
        )
        for item in session.get("events") or []
        if isinstance(item, dict) and item.get("side") == "buy" and item.get("status") == "filled"
    ]
    return {
        "id": "lab",
        "source": f"simulation lab {session.get('id')}",
        "text": (
            f"Label {session.get('label')}. Scenario {session.get('scenario')}. "
            f"Started at {session.get('starting_usd')} USD and ended at "
            f"{session.get('ending_usd')} USD. "
            f"Buys {session.get('buys')}. Sells {session.get('sells')}. "
            f"{' '.join(buys) if buys else 'No buy was filled in this session.'} "
            f"Realized P&L {session.get('realized_pnl_usd')} USD. "
            f"Unrealized P&L {session.get('unrealized_pnl_usd')} USD. "
            f"Recorded modeled costs {session.get('costs_usd')} USD. "
            f"Exposure {session.get('exposure_usd')} USD. "
            f"Maximum drawdown {session.get('max_drawdown')}. "
            f"Cash comparison {comparisons.get('cash')} USD. "
            f"SPY buy-and-hold price-only {comparisons.get('spy_buy_hold_price_only')}. "
            f"Approval delivery {approval.get('delivery') or approval.get('status')}. "
            f"Approval results: {decisions or 'none'}. "
            f"Token reuse blocked: {approval.get('token_reuse_blocked')}. "
            f"Accounting reconciliation {((session.get('reconciliation') or {}).get('status'))}. "
            f"{session.get('limitations')} This is not forward profit and it did not "
            "change the forward book."
        ),
    }


def _deterministic(question: str, evidence: list[dict[str, str]]) -> dict[str, Any]:
    by_id = {item["id"]: item["text"] for item in evidence}
    folded = question.lower()
    chosen: list[str] = []
    follow_ups: list[str] = []
    for words, ids, suggestions in _TOPICS:
        if any(re.search(rf"\b{re.escape(word)}\b", folded) for word in words):
            chosen.extend(ids)
            follow_ups.extend(suggestions)
    if not chosen:
        chosen = ["trading.status", "data.sip", "portfolio"]
        follow_ups = ["Why are there no trades yet?", "Are my prices up to date?"]
    unique = [item for item in dict.fromkeys(chosen) if item in by_id]
    if "lab" in unique:
        unique = ["lab", *[item for item in unique if item != "lab"]]
    sentences = [by_id[item] for item in unique]
    return {
        "answer": " ".join(sentences),
        "evidence_ids": unique,
        "follow_ups": list(dict.fromkeys(follow_ups)),
    }


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
    history: list[dict[str, str]],
) -> dict[str, Any] | None:
    packet = "\n".join(f"[{item['id']}] {item['text']}" for item in evidence)
    messages: list[dict[str, str]] = [{"role": "system", "content": _SYSTEM}]
    for turn in history[-_HISTORY_TURNS:]:
        role = turn.get("role")
        content = str(turn.get("content") or "")[:800]
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": f"Evidence:\n{packet}\n\nQuestion: {question}"})
    try:
        parsed = provider.chat_json(model, messages, _SCHEMA, timeout=60, num_ctx=8192)
    except OllamaError:
        return None
    answer = str(parsed.get("answer") or "").strip()
    raw_ids = parsed.get("used_evidence_ids")
    if not answer or not isinstance(raw_ids, list):
        return None
    known = {item["id"] for item in evidence}
    used = [str(item).strip("[]") for item in raw_ids if str(item).strip("[]") in known]
    if not used:
        return None
    allowed = "\n".join(item["text"] for item in evidence) + "\n" + question
    if _unsupported_numbers(answer, allowed):
        return None
    raw_follow = parsed.get("follow_ups")
    follow_ups = (
        [str(item)[:120] for item in raw_follow if isinstance(item, str) and item.strip()]
        if isinstance(raw_follow, list)
        else []
    )
    follow_ups = [item for item in follow_ups if not _unsupported_numbers(item, allowed)]
    return {"answer": answer, "evidence_ids": used, "follow_ups": follow_ups[:3]}


def _unsupported_numbers(answer: str, evidence: str) -> list[str]:
    bad: list[str] = []
    for token in _NUMBER.findall(answer):
        plain = token.replace(",", "")
        if plain in {"0", "1"}:
            continue
        if token not in evidence and plain not in evidence:
            bad.append(token)
    return bad
