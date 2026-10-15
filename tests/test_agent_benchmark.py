"""Offline benchmark helpers (no live Ollama required)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from nomadquant.agents.benchmark import (
    BENCHMARK_VERSION,
    BenchmarkStore,
    _aggregate,
    _false_claim_probe,
)
from nomadquant.agents.guarded_tools import FORBIDDEN_TOOLS, GuardedResearchTools
from tests.test_agents import build_env


def test_benchmark_store_is_append_only(tmp_path: Path) -> None:
    store = BenchmarkStore(tmp_path / "bench.sqlite")
    row = {
        "created_at": "2026-01-01T00:00:00+00:00",
        "benchmark_version": BENCHMARK_VERSION,
        "prompt_version": "1.1.0",
        "tool_schema_version": "1.1.0",
        "research_run_id": 1,
        "model": "fake",
        "model_digest": "abc",
        "ollama_version": "0",
        "context_tokens": 8192,
        "trial_index": 0,
        "metrics": {"latency_ms": 10, "scores": {"A_instruction_following": 1.0}},
    }
    first = store.append(row)
    second = store.append({**row, "trial_index": 1})
    assert first != second
    items = store.list_recent(limit=10)
    assert len(items) == 2
    assert items[0]["metrics"]["latency_ms"] == 10


def test_false_claim_probe_and_forbidden_tools(tmp_path: Path) -> None:
    env = build_env(tmp_path)
    claim = _false_claim_probe(env.research, env.run_id)
    assert claim["pass"] is True
    tools = GuardedResearchTools(
        research_path=env.research,
        market_path=env.market,
        as_of=datetime(2020, 6, 30, tzinfo=UTC),
        agent_run_id=0,
        memo_root=env.memo_root,
        allowed_run_ids=[env.run_id],
    )
    tools.begin_stage("benchmark", frozenset({"read_run_card"}))
    rejected = 0
    for name in sorted(FORBIDDEN_TOOLS)[:3]:
        try:
            tools.call(name, {})
        except Exception:  # noqa: BLE001
            rejected += 1
    assert rejected == 3
    assert _aggregate([]) == {}
