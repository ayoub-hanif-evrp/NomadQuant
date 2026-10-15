"""CLI for local AI research agents. Retrospective review only; no trading."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from nomadquant.agents.benchmark import BenchmarkStore, run_benchmark
from nomadquant.agents.constants import PROMPT_VERSION, TOOL_SCHEMA_VERSION
from nomadquant.agents.ollama import OllamaError, OllamaProvider
from nomadquant.agents.store import AgentStore, AgentStoreError
from nomadquant.agents.workflow import run_research_review
from nomadquant.audit import AuditLog
from nomadquant.config import Settings, get_settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="nomadquant-agent")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Review a stored research run with local agents.")
    run_parser.add_argument("--research-run-id", required=True, type=int)
    run_parser.add_argument("--model", default="", help="Ollama model. Defaults to OLLAMA_MODEL.")

    sub.add_parser("status", help="Show Ollama availability and recent agent runs.")

    inspect_parser = sub.add_parser("inspect", help="Show one agent run in full.")
    inspect_parser.add_argument("--run-id", required=True, type=int)

    resume_parser = sub.add_parser("resume", help="Resume an unfinished agent run.")
    resume_parser.add_argument("--run-id", required=True, type=int)
    resume_parser.add_argument("--model", default="", help="Must match the original run.")

    bench = sub.add_parser("benchmark", help="Benchmark installed Ollama models on fixed tasks.")
    bench.add_argument("--models", required=True, help="Comma-separated Ollama model names.")
    bench.add_argument("--research-run-id", required=True, type=int)
    bench.add_argument("--trials", type=int, default=1)
    bench.add_argument(
        "--context",
        type=int,
        default=8192,
        help="Recorded context length for this trial (4096/8192/16384).",
    )
    bench.add_argument(
        "--skip-workflow",
        action="store_true",
        help="Skip the full three-stage workflow (faster probes only).",
    )

    args = parser.parse_args(argv)
    settings = get_settings()
    code = _dispatch(args, settings)
    if code:
        raise SystemExit(code)


def _dispatch(args: argparse.Namespace, settings: Settings) -> int:
    if args.command == "status":
        return _status(settings)
    if args.command == "inspect":
        detail = AgentStore(settings.agents_path).get_run_detail(args.run_id)
        if detail is None:
            print(f"error: agent run {args.run_id} not found", file=sys.stderr)
            return 1
        _print(detail)
        return 0
    if args.command == "run":
        return _run(settings, args.research_run_id, args.model or settings.ollama_model, None)
    if args.command == "resume":
        store = AgentStore(settings.agents_path)
        existing = store.get_run(args.run_id)
        if existing is None:
            print(f"error: agent run {args.run_id} not found", file=sys.stderr)
            return 1
        model = args.model or existing["model"]
        return _run(settings, int(existing["research_run_id"]), model, args.run_id)
    if args.command == "benchmark":
        return _benchmark(settings, args)
    print(f"error: unsupported command {args.command}", file=sys.stderr)
    return 2


def _status(settings: Settings) -> int:
    provider = OllamaProvider(settings.ollama_base_url)
    store = AgentStore(settings.agents_path)
    health = provider.health()
    models: list[dict[str, Any]] = []
    if health["available"]:
        try:
            models = provider.list_model_details()
        except OllamaError:
            models = [{"name": name} for name in health["models"]]
    benches: list[dict[str, Any]] = []
    bench_path = Path(settings.agent_benchmark_path)
    if bench_path.exists():
        benches = BenchmarkStore(bench_path).list_recent(limit=10)
    _print(
        {
            "ollama": health,
            "configured_model": settings.ollama_model,
            "installed_models": models,
            "prompt_version": PROMPT_VERSION,
            "tool_schema_version": TOOL_SCHEMA_VERSION,
            "trading_mode": settings.trading_mode,
            "recent_runs": [
                {
                    key: item[key]
                    for key in ("id", "status", "research_run_id", "model", "verdict", "created_at")
                }
                for item in store.list_runs(limit=10)
            ],
            "recent_benchmarks": benches,
        }
    )
    return 0 if health["available"] else 1


def _benchmark(settings: Settings, args: argparse.Namespace) -> int:
    models = [item.strip() for item in str(args.models).split(",") if item.strip()]
    if not models:
        print("error: provide at least one model", file=sys.stderr)
        return 2
    if args.context not in {4096, 8192, 16384}:
        print("error: --context must be 4096, 8192, or 16384", file=sys.stderr)
        return 2
    provider = OllamaProvider(settings.ollama_base_url, default_timeout=240.0)
    try:
        report = run_benchmark(
            models=models,
            research_run_id=args.research_run_id,
            research_path=settings.research_path,
            market_path=settings.market_data_path,
            memo_root=settings.agent_memo_root,
            agents_path=settings.agents_path,
            benchmark_path=settings.agent_benchmark_path,
            audit_path=settings.database_path,
            provider=provider,
            trials=max(1, args.trials),
            context_tokens=args.context,
            include_full_workflow=not args.skip_workflow,
        )
    except OllamaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print(report)
    return 0


def _run(settings: Settings, research_run_id: int, model: str, resume_run_id: int | None) -> int:
    if not model:
        print("error: provide --model or set OLLAMA_MODEL", file=sys.stderr)
        return 2
    provider = OllamaProvider(settings.ollama_base_url)
    health = provider.health()
    if not health["available"]:
        print(f"error: {health['error']}", file=sys.stderr)
        return 1
    if model not in health["models"]:
        print(
            f"error: model {model!r} is not installed. Run `ollama pull {model}`.", file=sys.stderr
        )
        return 1
    store = AgentStore(settings.agents_path)
    audit = AuditLog(settings.database_path, settings.secret_values)
    try:
        detail = run_research_review(
            research_run_id,
            model,
            research_path=settings.research_path,
            market_path=settings.market_data_path,
            memo_root=settings.agent_memo_root,
            store=store,
            provider=provider,
            audit=audit,
            resume_run_id=resume_run_id,
        )
    except AgentStoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print(detail)
    return 0 if detail["status"] == "succeeded" else 1


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
