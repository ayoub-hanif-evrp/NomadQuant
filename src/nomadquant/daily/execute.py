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
    _insert_order,
    _listed_orders,
    _money,
    _orders,
    _pretrade,
    _recheck_before_send,
    _recover_existing,
    _refused,
    _send,
    _sleeve,
    _untracked,
)
from nomadquant.config import PAPER_API_URL, Settings
from nomadquant.daily.authorization import authorization_status
from nomadquant.daily.engine import primary_candidate
from nomadquant.daily.registry import SPECS, UNIVERSE
from nomadquant.risk.engine import RiskEngine
from nomadquant.risk.ledger import InternalLedger
from nomadquant.risk.policy import POLICY_VERSION, RiskPolicy
from nomadquant.risk.schemas import AccountMetrics, Proposal


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
    auth = authorization_status(settings, now=clock)
    if not auth["enabled"]:
        return _refused(str(auth["reason"]))
    if settings.alpaca_base_url != PAPER_API_URL or settings.allow_order_submission:
        return _refused("non_paper_url")
    action = str(decision.get("action") or "HOLD")
    symbol = str(decision.get("symbol") or "")
    strategy_id = str(decision.get("strategy_id") or "")
    signal = decision.get("signal_session")
    if action not in {"BUY", "SELL"} or symbol not in UNIVERSE or strategy_id not in SPECS:
        return _refused("hold")
    if not isinstance(signal, str):
        return _refused("missing_signal")
    from datetime import date

    confirmed = primary_candidate(prices, date.fromisoformat(signal))
    if (
        confirmed is None
        or confirmed["strategy_id"] != strategy_id
        or confirmed["symbol"] != symbol
        or confirmed["action"] != action
    ):
        return _refused("fabricated_signal")
    notional = Decimal(str(decision.get("notional_usd") or "0"))
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
    orders = _orders(settings.paper_path)
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
    strategy_orders = [row for row in orders if row.get("purpose") != "connectivity"]
    strategy = _exposure(strategy_orders)
    if action == "SELL":
        owned = strategy["qty"].get(symbol, Decimal("0"))
        broker_qty = _broker_qty(client, symbol)
        if owned <= 0 or broker_qty is None or broker_qty < owned:
            return _refused("connectivity_position_isolated")
    else:
        remaining = _sleeve(cash, buying_power, full["capital"])["remaining"]
        if notional > remaining:
            return _refused("sleeve_exceeded")
    if _strategy_loss(strategy_orders) >= Decimal("20"):
        return _refused("strategy_loss_stop")
    verdict = _risk(decision, symbol, action, notional, quote, clock)
    if verdict is not None:
        return _refused(verdict)
    fresh = _recheck_before_send(settings, client, symbol, quote_client, now)
    if fresh is not None:
        return _refused(fresh)
    _insert_order(
        settings.paper_path,
        client_order_id=client_order_id,
        purpose="strategy",
        symbol=symbol,
        side=action.lower(),
        notional=notional,
        created_at=clock.isoformat(),
        decision_id=f"{strategy_id}:{signal}:{symbol}:{action.lower()}",
        counts_as_strategy_pnl=True,
    )
    result = _send(settings, client, client_order_id, symbol, action.lower(), notional)
    result["counts_as_strategy_pnl"] = True
    result["connectivity_excluded"] = True
    return result


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
        if str(row.get("purpose")) != "strategy" or str(row.get("broker_status")) in released:
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


def _strategy_loss(orders: list[dict[str, Any]]) -> Decimal:
    loss = Decimal("0")
    for row in orders:
        if row.get("broker_status") != "filled" or row.get("side") != "buy":
            continue
        notional = _money(row.get("notional_usd")) or Decimal("0")
        qty = _money(row.get("filled_qty")) or Decimal("0")
        price = _money(row.get("filled_avg_price")) or Decimal("0")
        loss += max(Decimal("0"), notional - qty * price)
    return loss


def _risk(
    decision: dict[str, Any],
    symbol: str,
    action: str,
    notional: Decimal,
    quote: dict[str, Any] | None,
    now: datetime,
) -> str | None:
    if quote is None:
        return "missing_quote"
    from nomadquant.broker.paper_pilot import _as_datetime

    touch = _money(quote.get("ask"))
    if touch is None or touch <= 0:
        return "missing_quote"
    quantity = (notional / touch).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
    if quantity <= 0:
        return "risk_not_approved"
    proposal = Proposal(
        id=str(decision.get("strategy_id")),
        source=str(decision.get("strategy_id")),
        symbol=symbol,
        side="buy" if action == "BUY" else "sell",
        quantity=quantity,
        as_of=now,
    )
    prices = {
        symbol: {
            "price": touch,
            "as_of": _as_datetime(quote.get("market_timestamp")),
            "feed": quote.get("feed"),
            "first_retrieved_at": _as_datetime(quote.get("retrieved_at")),
            "bar_kind": "quote",
        }
    }
    ledger = InternalLedger(cash_usd=Decimal("100"), holdings={})
    account = AccountMetrics(
        realized_pnl_today_usd=Decimal("0"),
        equity_usd=Decimal("100"),
        peak_equity_usd=Decimal("100"),
    )
    result = RiskEngine(RiskPolicy()).evaluate(
        proposal, ledger, prices, account=account, now=now, clock="prospective", store=None
    )
    if result.verdict != "APPROVE" or result.policy_version != POLICY_VERSION:
        return "risk_not_approved"
    return None
