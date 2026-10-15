"""CLI for the local shadow research cycle. Never submits broker orders."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from typing import Any

from nomadquant.config import Settings, get_settings
from nomadquant.shadow.cycle import LABEL_FORWARD, LABEL_RETRO, run_shadow_cycle
from nomadquant.shadow.store import ShadowStore


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="nomadquant-shadow")
    sub = parser.add_subparsers(dest="command", required=True)

    cycle = sub.add_parser("cycle", help="Run one shadow research cycle.")
    cycle.add_argument("--mode", choices=["dry-run", "apply"], default="dry-run")
    cycle.add_argument(
        "--label",
        choices=[LABEL_FORWARD, LABEL_RETRO],
        default=LABEL_FORWARD,
        help="forward_shadow=prospective; retrospective_replay=labeled replay only.",
    )
    cycle.add_argument("--signal-session", default="", help="Optional YYYY-MM-DD override.")

    sub.add_parser("status", help="Show shadow ledger and recent cycles.")

    history = sub.add_parser("history", help="List shadow cycles.")
    history.add_argument("--limit", type=int, default=20)

    replay = sub.add_parser("replay", help="Inspect one stored cycle.")
    replay.add_argument("--cycle-id", type=int, required=True)

    args = parser.parse_args(argv)
    settings = get_settings()
    code = _dispatch(args, settings)
    if code:
        raise SystemExit(code)


def _dispatch(args: argparse.Namespace, settings: Settings) -> int:
    if args.command == "status":
        store = ShadowStore(settings.shadow_path)
        snap = store.snapshot()
        _print(
            {
                "trading_state": "SHADOW_ONLY",
                "allow_order_submission": settings.allow_order_submission,
                "starting_capital_usd": str(snap["starting_capital_usd"]),
                "cash_usd": str(snap["cash_usd"]),
                "reserved_cash_usd": str(snap["reserved_cash_usd"]),
                "holdings": {k: str(v) for k, v in snap["holdings"].items()},
                "realized_pnl_usd": str(snap["realized_pnl_usd"]),
                "total_costs_usd": str(snap["total_costs_usd"]),
                "peak_equity_usd": str(snap["peak_equity_usd"]),
                "ledger_version": snap["version"],
                "cycle_count": store.count_cycles(),
                "recent": store.list_cycles(limit=5),
            }
        )
        return 0
    if args.command == "history":
        store = ShadowStore(settings.shadow_path)
        _print({"items": store.list_cycles(limit=args.limit), "total": store.count_cycles()})
        return 0
    if args.command == "replay":
        detail = ShadowStore(settings.shadow_path).get_cycle(args.cycle_id)
        if detail is None:
            print(f"error: cycle {args.cycle_id} not found", file=sys.stderr)
            return 1
        _print(detail)
        return 0
    if args.command == "cycle":
        signal = date.fromisoformat(args.signal_session) if args.signal_session else None
        detail = run_shadow_cycle(
            market_path=settings.market_data_path,
            shadow_path=settings.shadow_path,
            risk_path=settings.risk_path,
            mode=args.mode,
            signal_session=signal,
            label=args.label,
        )
        _print(detail)
        return 0 if detail.get("status") not in {"error"} else 1
    return 2


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
