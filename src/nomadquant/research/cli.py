"""CLI for offline research experiments."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from nomadquant.audit import AuditLog
from nomadquant.config import get_settings
from nomadquant.research.audit import audit_run
from nomadquant.research.replay import replay_run
from nomadquant.research.runner import load_config, run_experiment
from nomadquant.research.verify import verify_run


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="nomadquant-research")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Run a versioned experiment configuration.")
    run_parser.add_argument("--experiment", required=True, help="Path to experiment JSON.")

    replay_parser = sub.add_parser("replay", help="Replay stored simulated decisions.")
    replay_parser.add_argument("--run-id", required=True, type=int)

    verify_parser = sub.add_parser("verify", help="Verify a stored research run.")
    verify_parser.add_argument("--run-id", required=True, type=int)

    audit_parser = sub.add_parser("audit", help="Bounded look-ahead and missing-data audit.")
    audit_parser.add_argument("--run-id", required=True, type=int)

    args = parser.parse_args(argv)
    settings = get_settings()
    audit = AuditLog(settings.database_path, settings.secret_values)

    if args.command == "run":
        config = load_config(Path(args.experiment))
        result = run_experiment(
            config,
            market_path=settings.market_data_path,
            research_path=settings.research_path,
            audit=audit,
        )
        print(json.dumps(result, indent=2, default=str))
        return

    if args.command == "verify":
        result = verify_run(
            args.run_id,
            research_path=settings.research_path,
            market_path=settings.market_data_path,
        )
        print(json.dumps(result, indent=2, default=str))
        if result["verdict"] not in {"PASS", "NOT_EVALUABLE"}:
            raise SystemExit(1)
        return

    if args.command == "audit":
        result = audit_run(
            args.run_id,
            research_path=settings.research_path,
            market_path=settings.market_data_path,
        )
        print(json.dumps(result, indent=2, default=str))
        if result["status"] == "FAIL":
            raise SystemExit(1)
        return

    if args.command == "replay":
        result = replay_run(
            args.run_id,
            research_path=settings.research_path,
            market_path=settings.market_data_path,
        )
        print(json.dumps(result, indent=2, default=str))
        if not result["ok"]:
            raise SystemExit(1)
        return

    raise SystemExit(f"Unsupported command {args.command}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
