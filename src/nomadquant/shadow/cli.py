"""CLI for the local shadow research cycle. Never submits broker orders."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from typing import Any

from nomadquant.config import Settings, get_settings
from nomadquant.shadow.cycle import LABEL_FORWARD, LABEL_RETRO, run_shadow_cycle
from nomadquant.shadow.daily import run_daily_operation
from nomadquant.shadow.data_ops import data_check, data_sync
from nomadquant.shadow.gate import application_guard
from nomadquant.shadow.marks import value_forward_portfolio
from nomadquant.shadow.preflight import run_preflight, run_reconcile
from nomadquant.shadow.store import ShadowStore, shadow_path_for_label
from nomadquant.shadow.verify import verify_cycle
from nomadquant.shadow.worker import run_daily_worker


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="nomadquant-shadow")
    sub = parser.add_subparsers(dest="command", required=True)

    cycle = sub.add_parser("cycle", help="Run one shadow research cycle.")
    cycle.add_argument("--mode", choices=["dry-run", "apply"], default="dry-run")
    cycle.add_argument(
        "--label",
        choices=[LABEL_FORWARD, LABEL_RETRO],
        default=LABEL_FORWARD,
        help="forward_shadow=prospective; retrospective_replay=separate ledger only.",
    )
    cycle.add_argument(
        "--signal-session",
        default="",
        help="Optional YYYY-MM-DD. Forward mode rejects stale overrides.",
    )

    sub.add_parser("status", help="Show shadow ledger and valuation.")
    data = sub.add_parser("data-check", help="Report missing completed daily sessions.")
    data.add_argument("--feed", choices=["sip", "iex"], default="sip")
    sync = sub.add_parser("data-sync", help="Opt-in read-only incremental bar download.")
    sync.add_argument("--feed", choices=["sip", "iex"], required=True)
    sync.add_argument(
        "--revision-audit",
        action="store_true",
        help="Re-fetch the warm-up window to detect revisions. Not the missing-data path.",
    )

    sub.add_parser("preflight", help="Forward cycle readiness checks.")
    sub.add_parser("reconcile", help="Reconcile shadow ledger invariants.")

    sub.add_parser(
        "recover",
        help="Release interrupted reservations and deliver shadow outbox (explicit).",
    )

    daily = sub.add_parser("daily", help="Supervised daily procedure. Default is inspect.")
    daily.add_argument("--mode", choices=["inspect", "dry-run", "shadow-apply"], default="inspect")
    daily.add_argument(
        "--sync",
        action="store_true",
        help="Opt in to authenticated historical data sync. Off by default.",
    )
    daily.add_argument("--feed", choices=["sip", "iex"], default="sip")

    verify = sub.add_parser("verify", help="Independently check one stored shadow cycle.")
    verify.add_argument("--cycle-id", type=int, required=True)

    worker = sub.add_parser("worker", help="Daily shadow worker (inspect / dry-run / apply).")
    worker.add_argument(
        "--mode",
        choices=["inspect", "dry-run", "shadow-apply"],
        default="inspect",
        help="inspect=no mutations; dry-run=cycle dry-run; shadow-apply=apply+outbox.",
    )

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
    if args.command == "data-check":
        _print(data_check(settings, feed=args.feed))
        return 0
    if args.command == "data-sync":
        try:
            payload = data_sync(settings, feed=args.feed, revision_audit=bool(args.revision_audit))
        except Exception as exc:  # noqa: BLE001
            print(f"error: {exc}", file=sys.stderr)
            return 1
        _print(payload)
        return 0 if payload.get("status") != "ERROR" else 1
    if args.command == "daily":
        code, payload = run_daily_operation(
            settings,
            mode=args.mode,
            sync=bool(args.sync),
            feed=args.feed,
        )
        _print(payload)
        return code
    if args.command == "verify":
        report = verify_cycle(settings, args.cycle_id)
        _print(report)
        return 0 if report["status"] != "FAIL" else 1
    if args.command == "preflight":
        _print(run_preflight(settings))
        return 0
    if args.command == "reconcile":
        result = run_reconcile(settings)
        _print(result)
        return 0 if result.get("ok") else 1
    if args.command == "recover":
        return _run_recover(settings)
    if args.command == "worker":
        code, payload = run_daily_worker(settings, mode=args.mode)
        _print(payload)
        return code
    if args.command == "status":
        store = ShadowStore(settings.shadow_path, namespace="forward")
        snap = store.snapshot()
        valuation = value_forward_portfolio(snap, settings.market_data_path)
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
                "valuation": valuation.as_dict(),
                "recent": store.list_cycles(limit=5),
                "note": "Equity from backend valuation only. Not Alpaca.",
            }
        )
        return 0
    if args.command == "history":
        store = ShadowStore(settings.shadow_path, namespace="forward")
        _print({"items": store.list_cycles(limit=args.limit), "total": store.count_cycles()})
        return 0
    if args.command == "replay":
        detail = ShadowStore(settings.shadow_path, namespace="forward").get_cycle(args.cycle_id)
        if detail is None:
            print(f"error: cycle {args.cycle_id} not found", file=sys.stderr)
            return 1
        _print(detail)
        return 0
    if args.command == "cycle":
        signal = date.fromisoformat(args.signal_session) if args.signal_session else None
        if args.label == LABEL_FORWARD and signal is not None:
            print(
                "note: forward --signal-session overrides older than 5 days are blocked.",
                file=sys.stderr,
            )
        if args.mode == "apply" and args.label == LABEL_FORWARD:
            guard = application_guard(settings)
            if not guard["allowed"]:
                _print(
                    {
                        "status": "blocked",
                        "label": args.label,
                        "mode": args.mode,
                        "gate": guard,
                        "error_safe": "application_guard_refused",
                    }
                )
                return 1
        detail = run_shadow_cycle(
            market_path=settings.market_data_path,
            shadow_path=settings.shadow_path,
            risk_path=settings.risk_path,
            mode=args.mode,
            signal_session=signal,
            label=args.label,
        )
        if args.label == LABEL_RETRO:
            detail = {
                **detail,
                "shadow_db": str(shadow_path_for_label(settings.shadow_path, LABEL_RETRO)),
            }
        _print(detail)
        return 0 if detail.get("status") not in {"error", "blocked"} else 1
    return 2


def _run_recover(settings: Settings) -> int:
    store = ShadowStore(settings.shadow_path, namespace="forward")
    released = store.recover_interrupted()
    outbox: dict[str, Any] | None = None
    try:
        from nomadquant.shadow.outbox import deliver_outbox

        outbox = deliver_outbox(store, settings.risk_path)
    except Exception as exc:  # noqa: BLE001
        outbox = {"skipped": True, "reason": str(exc)}
    _print(
        {
            "trading_state": "SHADOW_ONLY",
            "allow_order_submission": False,
            "recovery": released,
            "outbox": outbox,
            "note": "Explicit recovery only. Never submits broker orders.",
        }
    )
    if outbox and outbox.get("errors"):
        return 1
    return 0


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
