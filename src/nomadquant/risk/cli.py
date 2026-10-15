"""CLI for the Phase 5A risk engine. Hypothetical evaluation only.

This CLI never submits an order and never talks to Alpaca. ``evaluate``
builds one ``Proposal`` from flags, evaluates it against the internal $100
ledger and policy defaults, prints the verdict, and records it in the
append-only risk store (unless the proposal id was already recorded, in
which case the duplicate rule rejects it).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from nomadquant.config import Settings, get_settings
from nomadquant.risk.engine import RiskEngine
from nomadquant.risk.ledger import InternalLedger
from nomadquant.risk.policy import RiskPolicy
from nomadquant.risk.schemas import Proposal
from nomadquant.risk.store import RiskStore, RiskStoreError


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="nomadquant-risk")
    sub = parser.add_subparsers(dest="command", required=True)

    evaluate_parser = sub.add_parser(
        "evaluate", help="Evaluate one hypothetical proposal. Never submits an order."
    )
    evaluate_parser.add_argument("--symbol", required=True)
    evaluate_parser.add_argument("--side", required=True, choices=("buy", "sell"))
    evaluate_parser.add_argument("--qty", required=True, help="Quantity, e.g. 0.01")
    evaluate_parser.add_argument("--price", required=True, help="Current price, e.g. 500")
    evaluate_parser.add_argument("--proposal-id", required=True)
    evaluate_parser.add_argument("--limit-price", default=None)
    evaluate_parser.add_argument("--as-of", default=None, help="ISO timestamp. Defaults to now.")
    evaluate_parser.add_argument("--price-as-of", default=None, help="ISO timestamp of the price.")
    evaluate_parser.add_argument("--feed", default="iex")
    evaluate_parser.add_argument("--source", default="cli")
    evaluate_parser.add_argument("--cash", default=None, help="Override ledger cash. Default 100.")
    evaluate_parser.add_argument(
        "--no-record", action="store_true", help="Do not persist the result."
    )

    sub.add_parser("status", help="Show policy defaults and the risk store summary.")

    args = parser.parse_args(argv)
    settings = get_settings()
    code = _dispatch(args, settings)
    if code:
        raise SystemExit(code)


def _dispatch(args: argparse.Namespace, settings: Settings) -> int:
    if args.command == "status":
        return _status(settings)
    if args.command == "evaluate":
        return _evaluate(args, settings)
    print(f"error: unsupported command {args.command}", file=sys.stderr)
    return 2


def _status(settings: Settings) -> int:
    policy = RiskPolicy()
    store = RiskStore(settings.risk_path)
    _print(
        {
            "policy": policy.as_dict(),
            "risk_path": settings.risk_path,
            "recorded_evaluations": store.count(),
            "trading_mode": settings.trading_mode,
        }
    )
    return 0


def _evaluate(args: argparse.Namespace, settings: Settings) -> int:
    try:
        quantity = Decimal(args.qty)
        price = Decimal(args.price)
        limit_price = None if args.limit_price is None else Decimal(args.limit_price)
        cash = Decimal("100") if args.cash is None else Decimal(args.cash)
    except InvalidOperation as exc:
        print(f"error: invalid decimal value: {exc}", file=sys.stderr)
        return 2

    now = datetime.now(UTC)
    as_of = now if args.as_of is None else datetime.fromisoformat(args.as_of)
    price_as_of = now if args.price_as_of is None else datetime.fromisoformat(args.price_as_of)

    proposal = Proposal(
        id=args.proposal_id,
        source=args.source,
        symbol=args.symbol,
        side=args.side,
        quantity=quantity,
        limit_price=limit_price,
        as_of=as_of,
    )
    ledger = InternalLedger.starting(cash)
    prices: dict[str, Any] = {
        proposal.symbol: {"price": price, "as_of": price_as_of, "feed": args.feed}
    }
    policy = RiskPolicy()
    store = RiskStore(settings.risk_path)
    result = RiskEngine(policy).evaluate(proposal, ledger, prices, store=store)

    if not args.no_record and not store.seen(proposal.id):
        try:
            store.record(proposal, result)
        except RiskStoreError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    _print(result.model_dump(mode="json"))
    return 0 if result.verdict == "APPROVE" else 1


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
