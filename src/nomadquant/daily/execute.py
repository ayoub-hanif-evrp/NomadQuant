"""Submit one authorized daily paper order. The default authorization is off."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from nomadquant.broker.paper_pilot import (
    _broker_qty,
    _exposure,
    _find,
    _listed_orders,
    _money,
    _orders,
    _pretrade,
    _quote_problem,
    _recheck_before_send,
    _recover_existing,
    _refused,
    _sleeve,
    _submit_claimed,
    _untracked,
    hold_submission,
)
from nomadquant.config import PAPER_API_URL, Settings
from nomadquant.daily.authorization import authorization_status, shared_emergency_stop
from nomadquant.daily.engine import primary_candidate
from nomadquant.daily.fills import load_executions
from nomadquant.daily.fingerprint import authoritative_disagreement, price_fingerprint
from nomadquant.daily.portfolio import build_portfolio
from nomadquant.daily.registry import INFLUENCE_POLICY, RISK_POLICY, SPECS, UNIVERSE
from nomadquant.daily.store import latest_decision, note_equity
from nomadquant.risk.engine import RiskEngine
from nomadquant.risk.ledger import InternalLedger
from nomadquant.risk.policy import RiskPolicy
from nomadquant.risk.schemas import AccountMetrics, Proposal

_PAPER_POLICY = RiskPolicy(version="1.3.0", max_qty_decimals=9)
_QTY_STEP = Decimal("0.000000001")


def submit_daily_paper_order(
    settings: Settings,
    *,
    decision: dict[str, Any],
    prices: dict[str, dict[Any, Decimal]],
    client: Any,
    quote_client: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    clock = now or datetime.now(UTC)
    stopped = shared_emergency_stop(settings, now=clock)
    if stopped is not None:
        return _refused(stopped)
    auth = authorization_status(settings, now=clock)
    if not auth["enabled"]:
        return _refused(str(auth["reason"]))
    stored = latest_decision(settings.daily_path)
    if stored is None:
        return _refused("untrusted_decision")
    action = str(stored.get("action") or "HOLD")
    symbol = str(stored.get("symbol") or "")
    strategy_id = str(stored.get("strategy_id") or "")
    signal = stored.get("signal_session")
    if decision.get("action") not in {None, action} or decision.get("strategy_id") not in {
        None,
        strategy_id,
    }:
        return _refused("untrusted_decision")
    if (
        stored.get("influence_policy") != INFLUENCE_POLICY
        or stored.get("risk_policy") != RISK_POLICY
    ):
        return _refused("policy_version_mismatch")
    expected_version = None if strategy_id not in SPECS else SPECS[strategy_id].version
    if stored.get("strategy_version") != expected_version:
        return _refused("policy_version_mismatch")
    if stored.get("missed_window") is True:
        return _refused("missed_window")
    execution = stored.get("execution_session")
    if execution != clock.astimezone(ZoneInfo("America/New_York")).date().isoformat():
        return _refused("ineligible_session")
    if settings.alpaca_base_url != PAPER_API_URL or settings.allow_order_submission:
        return _refused("non_paper_url")
    if action not in {"BUY", "SELL"} or symbol not in UNIVERSE or strategy_id not in SPECS:
        return _refused("hold")
    if not isinstance(signal, str):
        return _refused("missing_signal")
    from datetime import date

    feed = str(stored.get("market_feed") or "")
    if stored.get("price_fingerprint") != price_fingerprint(prices, feed=feed):
        return _refused("price_fingerprint_mismatch")
    decided_at = _decision_clock(stored.get("recorded_at"))
    if decided_at is None:
        return _refused("unverified_market_data")
    disagreed = authoritative_disagreement(
        settings, prices, feed=feed, decided_at=decided_at, now=clock
    )
    if disagreed is not None:
        return _refused(disagreed)
    orders = _orders(settings.paper_path)
    try:
        executions = load_executions(settings.paper_path)
    except Exception:  # noqa: BLE001
        return _refused("ledger_unreadable")
    held_book = build_portfolio(orders, executions=executions)
    strategy_held = any(Decimal(value) > 0 for value in held_book["strategy_qty"].values())
    if action == "SELL" and Decimal(held_book["connectivity_qty"]) > 0 and not strategy_held:
        return _refused("connectivity_position_isolated")
    symbols = _marked_symbols(held_book)
    quotes = _mark_quotes(settings, symbols, quote_client, clock)
    session_day = clock.astimezone(ZoneInfo("America/New_York")).date()
    marks = None if quotes is None else {symbol: quote["bid"] for symbol, quote in quotes.items()}
    book = build_portfolio(
        orders,
        {} if marks is None else marks,
        session=session_day,
        executions=executions,
    )
    if quotes is None and symbols:
        return _refused("portfolio_unreconciled")
    if book["disputed"]:
        return _refused("portfolio_disputed")
    if not book["marks_complete"]:
        return _refused("portfolio_unreconciled")
    if action == "BUY" and book["accounting_state"] != "verified":
        return _refused(str(book["accounting_reason"] or "accounting_unverified"))
    if action == "BUY" and book["loss_stop"]:
        return _refused("strategy_loss_stop")
    holdings = {key: Decimal(value) for key, value in book["strategy_qty"].items()}
    confirmed = primary_candidate(prices, date.fromisoformat(signal), holdings)
    if (
        confirmed is None
        or confirmed["strategy_id"] != strategy_id
        or confirmed["symbol"] != symbol
        or confirmed["action"] != action
    ):
        return _refused("fabricated_signal")
    notional = Decimal(str(stored.get("notional_usd") or "0"))
    cap = SPECS[strategy_id].notional_cap
    if action == "BUY" and (notional <= 0 or notional > cap):
        return _refused("sleeve_exceeded")
    if action == "SELL" and notional <= 0:
        notional = cap
    client_order_id = f"nq-daily-{strategy_id}-{signal}-{symbol}-{action.lower()}"
    try:
        existing = _find(settings.paper_path, client_order_id)
    except Exception:  # noqa: BLE001
        return _refused("ledger_unreadable")
    recovered = _recover_existing(settings, client, client_order_id, existing)
    if recovered is not None:
        return recovered
    quote = _trusted(settings, symbol, quote_client, clock)
    gate = _pretrade(client, symbol, quote, clock if now is not None else datetime.now(UTC))
    if gate is not None:
        return _refused(gate)
    if _session_limit(orders, clock):
        return _refused("session_order_limit")
    listed = _listed_orders(client)
    if listed is None:
        return _refused("broker_orders_unreadable")
    if _untracked(orders, listed):
        return _refused("untracked_broker_order")
    account = client.get_account()
    cash = _money(getattr(account, "cash", None))
    buying_power = _money(getattr(account, "buying_power", None))
    if cash is None or buying_power is None:
        return _refused("account_amounts_unreadable")
    full = _exposure(orders)
    owned = holdings.get(symbol, Decimal("0"))
    reserved_sell = Decimal(str(book["reserved_sell_qty"].get(symbol, "0")))
    sell_qty = owned - reserved_sell
    broker_qty = _broker_qty(client, symbol)
    if action == "SELL":
        if owned <= 0 and broker_qty is not None and broker_qty > 0:
            return _refused("connectivity_position_isolated")
        quantity = _floor_shares(sell_qty)
        residual = sell_qty - quantity
        if quantity <= 0 or quantity > sell_qty or broker_qty is None or broker_qty < quantity:
            return _refused(
                "quantity_below_precision" if quantity <= 0 else "connectivity_position_isolated"
            )
    else:
        remaining = _sleeve(cash, buying_power, full["capital"])["remaining"]
        if notional > remaining or Decimal(book["available_cash_usd"]) < notional:
            return _refused("sleeve_exceeded")
        touch = _money(quote.get("ask")) if quote else None
        if touch is None or touch <= 0:
            return _refused("missing_quote")
        quantity = (notional / touch).quantize(_QTY_STEP, rounding=ROUND_DOWN)
    if book["equity_usd"] is None:
        return _refused("portfolio_unreconciled")
    if action == "BUY" and book["realized_today_usd"] is None:
        return _refused("execution_history_incomplete")
    # A missing session figure must not block an authorized strategy exit.
    risk_book = book
    if action == "SELL" and book["realized_today_usd"] is None:
        risk_book = {**book, "realized_today_usd": "0"}
    peak = Decimal(
        note_equity(
            settings.daily_path,
            as_of=clock.isoformat(),
            equity=str(book["equity_usd"]),
            realized=str(book["realized_pnl_usd"]),
        )
    )
    verdict = _risk(stored, symbol, action, quantity, quotes, quote, clock, risk_book, peak)
    if verdict is not None:
        return _refused(verdict)
    fresh = _recheck_before_send(settings, client, symbol, quote_client, now)
    if fresh is not None:
        return _refused(fresh)
    refreshed = _trusted(settings, symbol, quote_client, clock)
    if action == "SELL":
        bid = None if refreshed is None else _money(refreshed.get("bid"))
        if bid is None or bid <= 0:
            return _refused("missing_quote")
        notional = (quantity * bid).quantize(Decimal("0.01"))
    verdict = _risk(stored, symbol, action, quantity, quotes, refreshed, clock, risk_book, peak)
    if verdict is not None:
        return _refused(verdict)
    with hold_submission():
        result = _submit_claimed(
            settings,
            client,
            client_order_id=client_order_id,
            purpose="strategy",
            symbol=symbol,
            side=action.lower(),
            notional=notional,
            created_at=clock.isoformat(),
            decision_id=f"{strategy_id}:{signal}:{symbol}:{action.lower()}",
            counts_as_strategy_pnl=True,
            qty=quantity if action == "SELL" else None,
            now=clock,
        )
    if action == "SELL":
        result["residual_qty"] = format(residual, "f")
    result["counts_as_strategy_pnl"] = True
    result["connectivity_excluded"] = True
    return result


def _floor_shares(quantity: Decimal) -> Decimal:
    """Alpaca fractional qty allows 9 decimal places. Never round a sell upward."""
    return quantity.quantize(_QTY_STEP, rounding=ROUND_DOWN)


def _decision_clock(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        return None
    return stamp


def _trusted(
    settings: Settings, symbol: str, quote_client: Any | None, now: datetime
) -> dict[str, Any] | None:
    from nomadquant.broker.paper_pilot import _trusted_quote

    return _trusted_quote(settings, symbol, quote_client, now)


def _session_limit(orders: list[dict[str, Any]], now: datetime) -> bool:
    day = now.astimezone(ZoneInfo("America/New_York")).date()
    released = {"canceled", "cancelled", "rejected", "expired"}
    count = 0
    for row in orders:
        status = str(row.get("broker_status"))
        filled = _money(row.get("filled_qty")) or Decimal("0")
        if str(row.get("purpose")) != "strategy":
            continue
        if status in released and filled <= 0:
            continue
        text = str(row.get("created_at") or "")
        try:
            created = datetime.fromisoformat(text)
        except ValueError:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if created.astimezone(ZoneInfo("America/New_York")).date() == day:
            count += 1
    return count >= 1


def _marked_symbols(book: dict[str, Any]) -> set[str]:
    symbols = {key for key, value in book["strategy_qty"].items() if Decimal(value) > 0}
    if Decimal(book["connectivity_qty"]) > 0:
        symbols.add("SPY")
    return symbols


def _mark_quotes(
    settings: Settings,
    symbols: set[str],
    quote_client: Any | None,
    now: datetime,
) -> dict[str, dict[str, Any]] | None:
    if not symbols:
        return {}
    found: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        quote = _trusted(settings, symbol, quote_client, now)
        if quote is None or _quote_problem(quote, symbol, now) is not None:
            return None
        bid = _money(quote.get("bid"))
        ask = _money(quote.get("ask"))
        if bid is None or ask is None or bid <= 0 or ask < bid:
            return None
        found[symbol] = {**quote, "bid": bid, "ask": ask}
    return found


def _risk(
    decision: dict[str, Any],
    symbol: str,
    action: str,
    quantity: Decimal,
    quotes: dict[str, dict[str, Any]] | None,
    quote: dict[str, Any] | None,
    now: datetime,
    book: dict[str, Any],
    peak: Decimal,
) -> str | None:
    if quote is None or quotes is None or quantity <= 0:
        return "missing_quote"
    from nomadquant.broker.paper_pilot import _as_datetime

    touch = _money(quote.get("bid") if action == "SELL" else quote.get("ask"))
    if touch is None or touch <= 0:
        return "missing_quote"
    proposal = Proposal(
        id=str(decision.get("strategy_id")),
        source=str(decision.get("strategy_id")),
        symbol=symbol,
        side="buy" if action == "BUY" else "sell",
        quantity=quantity,
        as_of=now,
    )
    prices: dict[str, Any] = {}
    for held, held_quote in quotes.items():
        prices[held] = {
            "price": held_quote["bid"],
            "as_of": _as_datetime(held_quote.get("market_timestamp")),
            "feed": held_quote.get("feed"),
            "first_retrieved_at": _as_datetime(held_quote.get("retrieved_at")),
            "bar_kind": "quote",
        }
    prices[symbol] = {
        "price": touch,
        "as_of": _as_datetime(quote.get("market_timestamp")),
        "feed": quote.get("feed"),
        "first_retrieved_at": _as_datetime(quote.get("retrieved_at")),
        "bar_kind": "quote",
    }
    cash = Decimal(str(book["available_cash_usd"]))
    holdings = {
        key: Decimal(value) for key, value in book["strategy_qty"].items() if Decimal(value) > 0
    }
    if action == "SELL" and quantity > holdings.get(symbol, Decimal("0")):
        return "risk_not_approved"
    equity = Decimal(str(book["equity_usd"]))
    ledger = InternalLedger(cash_usd=cash, holdings=holdings)
    account = AccountMetrics(
        realized_pnl_today_usd=Decimal(str(book["realized_today_usd"])),
        equity_usd=equity,
        peak_equity_usd=peak,
    )
    result = RiskEngine(_PAPER_POLICY).evaluate(
        proposal, ledger, prices, account=account, now=now, clock="prospective", store=None
    )
    if result.verdict != "APPROVE" or result.policy_version != _PAPER_POLICY.version:
        return "risk_not_approved"
    return None
