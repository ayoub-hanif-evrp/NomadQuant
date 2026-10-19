"""Alpaca paper orders against the current market. Fake money only.

Live trading endpoints are refused. Submission stays off until an unexpired
local authorization exists. A historical replay is not a fill and is not P&L.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from nomadquant.config import PAPER_API_URL, Settings
from nomadquant.marketdata.calendar import is_early_close, next_session, sessions_between
from nomadquant.risk.policy import ALLOWED_SYMBOLS, POLICY_VERSION, RiskPolicy
from nomadquant.shadow.cycle import STRATEGY_ID
from nomadquant.shadow.observed_quote import OBSERVED_QUOTE_MAX_AGE

LABEL = "ALPACA PAPER TRADING — FAKE MONEY"
CONNECTIVITY_LABEL = "CONNECTIVITY TEST"
CEILING = Decimal("100")
CONNECTIVITY_CAP = Decimal("5")
MAX_STRATEGY_NOTIONAL = Decimal("50")
ENABLE_PHRASE = "ENABLE_ALPACA_PAPER_ORDERS"
KILL_PHRASE = "DISABLE_ALPACA_PAPER_ORDERS"
CONNECTIVITY_PHRASE = "SUBMIT_ONE_FIVE_DOLLAR_PAPER_CONNECTIVITY_ORDER"
AUTOMATIC_PHRASE = "ENABLE_AUTOMATIC_PAPER_PILOT"
CONNECTIVITY_CLIENT_ID = "nq-connect-spy-buy-5"
_NY = ZoneInfo("America/New_York")
_OPEN = frozenset(
    {
        "prepared",
        "submitted",
        "unknown",
        "accepted",
        "partial",
        "pending_new",
        "new",
        "accepted_for_bidding",
    }
)
_RELEASED = frozenset({"canceled", "cancelled", "rejected", "expired"})
_COLUMNS = frozenset(
    {"broker_status", "broker_order_id", "filled_avg_price", "filled_qty", "remaining_qty"}
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_control (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    status TEXT NOT NULL,
    enabled_at TEXT,
    expires_at TEXT,
    killed_at TEXT
);
CREATE TABLE IF NOT EXISTS paper_automatic (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    status TEXT NOT NULL,
    expires_at TEXT,
    killed_at TEXT
);
CREATE TABLE IF NOT EXISTS paper_orders (
    client_order_id TEXT PRIMARY KEY,
    purpose TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    notional_usd TEXT NOT NULL,
    created_at TEXT NOT NULL,
    broker_status TEXT NOT NULL,
    broker_order_id TEXT,
    filled_avg_price TEXT,
    filled_qty TEXT,
    remaining_qty TEXT,
    decision_id TEXT,
    counts_as_strategy_pnl INTEGER NOT NULL
);
"""


def paper_status(
    settings: Settings, *, client: Any | None = None, now: datetime | None = None
) -> dict[str, Any]:
    """Read the paper account. Does not submit an order."""
    clock = now or datetime.now(UTC)
    base = _base(clock)
    if settings.alpaca_base_url != PAPER_API_URL:
        return {**base, "connected": False, "blocked": True, "reason": "non_paper_url"}
    trading = client if client is not None else _client(settings)
    if trading is None:
        return {**base, "connected": False, "blocked": True, "reason": "credentials_absent"}
    try:
        orders = _orders(settings.paper_path)
    except sqlite3.DatabaseError:
        return {**base, "connected": False, "blocked": True, "reason": "ledger_unreadable"}
    try:
        account = trading.get_account()
        market = trading.get_clock()
        asset = trading.get_asset("SPY")
        positions = list(trading.get_all_positions())
        broker_orders = _listed_orders(trading)
    except Exception as exc:  # noqa: BLE001 — broker text can contain secrets
        return {**base, "connected": False, "blocked": True, "reason": type(exc).__name__}
    if broker_orders is None:
        return {**base, "connected": True, "blocked": True, "reason": "broker_orders_unreadable"}
    cash = _money(getattr(account, "cash", None))
    equity = _money(getattr(account, "equity", None))
    buying_power = _money(getattr(account, "buying_power", None))
    if cash is None or equity is None or buying_power is None:
        return {**base, "connected": False, "blocked": True, "reason": "account_amounts_unreadable"}
    untracked = _untracked(orders, broker_orders)
    disagreement = untracked or _reconcile(settings, trading, orders)
    fresh = [] if disagreement else _orders_safe(settings.paper_path)
    exposure = _exposure(fresh)
    block_reason = "untracked_broker_order" if untracked else "ledger_disagreement"
    sleeve = (
        {"blocked": True, "remaining": Decimal("0"), "reason": block_reason}
        if disagreement
        else _sleeve(cash, buying_power, exposure["capital"])
    )
    blocked = sleeve["blocked"] or not bool(getattr(asset, "fractionable", False))
    return {
        **base,
        "connected": True,
        "blocked": blocked,
        "reason": sleeve["reason"],
        "market_open": _clock_problem(market, clock) is None,
        "market_timestamp": _stamp(getattr(market, "timestamp", None)),
        "quote_required_before_submit": True,
        "account_cash_usd": str(cash),
        "account_equity_usd": str(equity),
        "account_buying_power_usd": str(buying_power),
        "buying_power_ignored": True,
        "sleeve_usd": "100",
        "sleeve_remaining_usd": str(sleeve["remaining"]),
        "attributed_qty": {key: str(value) for key, value in exposure["qty"].items()},
        "spy_fractionable": bool(getattr(asset, "fractionable", False)),
        "spy_tradable": bool(getattr(asset, "tradable", False)),
        "positions": [_position(item) for item in positions],
        "broker_orders": [_public_broker_order(item) for item in broker_orders],
        "orders": [_public_order(row) for row in _orders_safe(settings.paper_path)],
        "strategy_pnl": "not_started",
        "authorization": _authorization(settings.paper_path, clock),
        "automatic_pilot": _automatic(settings.paper_path, clock),
        "submission_enabled": bool(_authorization(settings.paper_path, clock)["enabled"]),
        "ready_for_first_order": False,
        "schedule_installed": False,
        "first_order_authorization": (
            "During a regular session, enable paper orders for at most 24 hours with "
            f"{ENABLE_PHRASE}, then authorize one connectivity order with "
            f"{CONNECTIVITY_PHRASE}. A fresh bid/ask is required at that moment. "
            "No order is sent until then."
        ),
    }


def enable_paper_orders(
    settings: Settings, *, confirm: str, hours: int, now: datetime | None = None
) -> dict[str, Any]:
    """Arm manual paper submission. This does not submit an order."""
    clock = now or datetime.now(UTC)
    if confirm != ENABLE_PHRASE:
        raise ValueError("Paper orders stay disabled without the exact enable phrase.")
    if hours < 1 or hours > 24:
        raise ValueError("Paper authorization must expire within 24 hours.")
    if settings.alpaca_base_url != PAPER_API_URL or settings.allow_order_submission:
        raise ValueError("Paper authorization refuses a live endpoint or the live order flag.")
    expires = (clock + timedelta(hours=hours)).isoformat()
    _write_control(
        settings.paper_path,
        status="enabled",
        enabled_at=clock.isoformat(),
        expires_at=expires,
        killed_at=None,
    )
    return {"enabled": True, "expires_at": expires, "orders_sent": 0}


def kill_paper_orders(
    settings: Settings, *, confirm: str, now: datetime | None = None
) -> dict[str, Any]:
    clock = now or datetime.now(UTC)
    if confirm != KILL_PHRASE:
        raise ValueError("Kill switch phrase does not match.")
    current = _control(settings.paper_path)
    _write_control(
        settings.paper_path,
        status="killed",
        enabled_at=current.get("enabled_at"),
        expires_at=current.get("expires_at"),
        killed_at=clock.isoformat(),
    )
    _write_automatic(
        settings.paper_path, status="killed", expires_at=None, killed_at=clock.isoformat()
    )
    return {"enabled": False, "killed": True, "automatic_pilot": False}


def submit_connectivity_order(
    settings: Settings,
    *,
    confirm: str,
    client: Any,
    quote: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """One SPY paper buy of $5, labeled as a connectivity test."""
    clock = now or datetime.now(UTC)
    if confirm != CONNECTIVITY_PHRASE:
        return _refused("authorization_missing")
    auth = _authorization(settings.paper_path, clock)
    if not auth["enabled"]:
        return _refused(str(auth["reason"]))
    if settings.alpaca_base_url != PAPER_API_URL:
        return _refused("non_paper_url")
    try:
        existing = _find(settings.paper_path, CONNECTIVITY_CLIENT_ID)
    except sqlite3.DatabaseError:
        return _refused("ledger_unreadable")
    if existing is not None:
        return _confirm_broker_record(settings, client, CONNECTIVITY_CLIENT_ID)
    gate = _pretrade(client, "SPY", quote, clock)
    if gate is not None:
        return _refused(gate)
    listed = _listed_orders(client)
    if listed is None:
        return _refused("broker_orders_unreadable")
    if _untracked(_orders(settings.paper_path), listed):
        return _refused("untracked_broker_order")
    account = client.get_account()
    cash = _money(getattr(account, "cash", None))
    buying_power = _money(getattr(account, "buying_power", None))
    if cash is None or buying_power is None:
        return _refused("account_amounts_unreadable")
    exposure = _exposure(_orders(settings.paper_path))
    remaining = _sleeve(cash, buying_power, exposure["capital"])["remaining"]
    if CONNECTIVITY_CAP > remaining:
        return _refused("sleeve_exceeded")
    _insert_order(
        settings.paper_path,
        client_order_id=CONNECTIVITY_CLIENT_ID,
        purpose="connectivity",
        symbol="SPY",
        side="buy",
        notional=CONNECTIVITY_CAP,
        created_at=clock.isoformat(),
        decision_id=CONNECTIVITY_CLIENT_ID,
        counts_as_strategy_pnl=False,
    )
    return _send(settings, client, CONNECTIVITY_CLIENT_ID, "SPY", "buy", CONNECTIVITY_CAP)


def submit_strategy_paper_order(
    settings: Settings,
    *,
    evidence: dict[str, Any] | None,
    client: Any,
    quote: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Submit one registered-strategy paper order. A bare APPROVE is not evidence."""
    clock = now or datetime.now(UTC)
    auth = _authorization(settings.paper_path, clock)
    if not auth["enabled"]:
        return _refused(str(auth["reason"]))
    problem = _validate_strategy_evidence(evidence or {}, clock)
    if problem is not None:
        return _refused(problem)
    assert evidence is not None
    symbol = str(evidence["symbol"])
    side = str(evidence["side"])
    notional = Decimal(str(evidence["notional_usd"]))
    decision_id = str(evidence["decision_id"])
    client_order_id = "nq-strategy-" + decision_id.replace(":", "-")
    try:
        existing = _find(settings.paper_path, client_order_id)
    except sqlite3.DatabaseError:
        return _refused("ledger_unreadable")
    if existing is not None:
        return _confirm_broker_record(settings, client, client_order_id)
    gate = _pretrade(client, symbol, quote, clock)
    if gate is not None:
        return _refused(gate)
    listed = _listed_orders(client)
    if listed is None:
        return _refused("broker_orders_unreadable")
    if _untracked(_orders(settings.paper_path), listed):
        return _refused("untracked_broker_order")
    if settings.alpaca_base_url != PAPER_API_URL:
        return _refused("non_paper_url")
    account_cash = _money(getattr(client.get_account(), "cash", None))
    buying_power = _money(getattr(client.get_account(), "buying_power", None))
    if account_cash is None or buying_power is None:
        return _refused("account_amounts_unreadable")
    exposure = _exposure(_orders(settings.paper_path))
    if side == "sell":
        bid = _money((quote or {}).get("bid"))
        if bid is None or bid <= 0:
            return _refused("missing_quote")
        owned = exposure["qty"].get(symbol, Decimal("0"))
        broker_qty = _broker_qty(client, symbol)
        if broker_qty is None or owned <= 0 or broker_qty < owned:
            return _refused("holdings_unconfirmed")
        available = owned * bid - _open_sell_notional(_orders(settings.paper_path), symbol)
        if notional > available:
            return _refused("sell_exceeds_holdings")
    else:
        remaining = _sleeve(account_cash, buying_power, exposure["capital"])["remaining"]
        if notional > remaining:
            return _refused("sleeve_exceeded")
    _insert_order(
        settings.paper_path,
        client_order_id=client_order_id,
        purpose="strategy",
        symbol=symbol,
        side=side,
        notional=notional,
        created_at=clock.isoformat(),
        decision_id=decision_id,
        counts_as_strategy_pnl=True,
    )
    return _send(settings, client, client_order_id, symbol, side, notional)


def enable_automatic_paper_pilot(
    settings: Settings, *, confirm: str, hours: int, now: datetime | None = None
) -> dict[str, Any]:
    """Separate switch. Calling this is not scheduled and does not submit."""
    clock = now or datetime.now(UTC)
    if confirm != AUTOMATIC_PHRASE:
        raise ValueError("Automatic paper pilot stays off without the exact phrase.")
    if hours < 1 or hours > 24:
        raise ValueError("Automatic paper authorization must expire within 24 hours.")
    if not _authorization(settings.paper_path, clock)["enabled"]:
        raise ValueError("Enable the paper-order switch before the automatic pilot.")
    expires = (clock + timedelta(hours=hours)).isoformat()
    _write_automatic(settings.paper_path, status="enabled", expires_at=expires, killed_at=None)
    return {"enabled": True, "expires_at": expires, "orders_sent": 0, "schedule_installed": False}


def run_automatic_paper_pilot(
    settings: Settings, *, client: Any, now: datetime | None = None
) -> dict[str, Any]:
    """Describe the unattended path. It does not submit while the switch is off."""
    clock = now or datetime.now(UTC)
    steps = [
        "current_market_data",
        "registered_monthly_signal",
        "risk_checks",
        "sleeve_sizing",
        "alpaca_paper_order",
        "broker_reconciliation",
        "post_trade_email",
    ]
    if not _automatic(settings.paper_path, clock)["enabled"]:
        return {
            "submitted": False,
            "reason": "automatic_pilot_disabled",
            "steps": steps,
            "schedule_installed": False,
        }
    return {
        "submitted": False,
        "reason": "no_eligible_monthly_signal",
        "steps": steps,
        "schedule_installed": False,
        "client_used": client is not None,
    }


def _pretrade(client: Any, symbol: str, quote: dict[str, Any] | None, now: datetime) -> str | None:
    try:
        market = client.get_clock()
        asset = client.get_asset(symbol)
    except Exception as exc:  # noqa: BLE001
        return f"broker_unread:{type(exc).__name__}"
    clock_problem = _clock_problem(market, now)
    if clock_problem is not None:
        return clock_problem
    if not bool(getattr(asset, "fractionable", False)) or not bool(
        getattr(asset, "tradable", False)
    ):
        return "asset_not_fractionable"
    return _quote_problem(quote, symbol, now)


def _clock_problem(market: Any, now: datetime) -> str | None:
    if not bool(getattr(market, "is_open", False)):
        return "market_not_open"
    stamped = _as_datetime(getattr(market, "timestamp", None))
    if stamped is None or abs(now - stamped) > OBSERVED_QUOTE_MAX_AGE:
        return "stale_clock"
    local = stamped.astimezone(_NY)
    if local.date() != now.astimezone(_NY).date():
        return "previous_session"
    close_hour = 13 if is_early_close(local.date()) else 16
    minute = local.hour * 60 + local.minute
    if minute < 9 * 60 + 30 or minute >= close_hour * 60:
        return "outside_regular_hours"
    return None


def _quote_problem(quote: dict[str, Any] | None, symbol: str, now: datetime) -> str | None:
    if not quote:
        return "missing_quote"
    if str(quote.get("symbol") or "") != symbol:
        return "missing_quote"
    bid = _money(quote.get("bid"))
    ask = _money(quote.get("ask"))
    if bid is None or ask is None or bid <= 0 or ask <= 0 or bid > ask:
        return "missing_quote"
    market_time = _as_datetime(quote.get("market_timestamp"))
    retrieved = _as_datetime(quote.get("retrieved_at"))
    if market_time is None or retrieved is None:
        return "stale_quote"
    if retrieved > now + timedelta(seconds=2) or now - retrieved > OBSERVED_QUOTE_MAX_AGE:
        return "stale_quote"
    if now - market_time > OBSERVED_QUOTE_MAX_AGE:
        return "stale_quote"
    if market_time.astimezone(_NY).date() != now.astimezone(_NY).date():
        return "stale_quote"
    return None


def _validate_strategy_evidence(evidence: dict[str, Any], now: datetime) -> str | None:
    required = (
        "strategy_id",
        "signal_session",
        "execution_session",
        "decision_id",
        "symbol",
        "side",
        "notional_usd",
        "risk_verdict",
        "policy_hash",
        "policy_version",
    )
    if any(evidence.get(key) in (None, "") for key in required):
        return "untrusted_strategy_approval"
    if evidence.get("strategy_id") != STRATEGY_ID or evidence.get("risk_verdict") != "APPROVE":
        return "untrusted_strategy_approval"
    policy = RiskPolicy()
    if (
        evidence.get("policy_hash") != policy.policy_hash()
        or evidence.get("policy_version") != POLICY_VERSION
    ):
        return "untrusted_strategy_approval"
    symbol = str(evidence.get("symbol"))
    side = str(evidence.get("side"))
    if symbol not in ALLOWED_SYMBOLS or side not in {"buy", "sell"}:
        return "symbol_or_side_refused"
    expected = f"{STRATEGY_ID}:{evidence.get('signal_session')}:{symbol}:{side}"
    if evidence.get("decision_id") != expected:
        return "untrusted_strategy_approval"
    try:
        signal = date.fromisoformat(str(evidence["signal_session"]))
        execution = date.fromisoformat(str(evidence["execution_session"]))
        notional = Decimal(str(evidence["notional_usd"]))
    except (ValueError, InvalidOperation):
        return "untrusted_strategy_approval"
    if notional <= 0 or notional > MAX_STRATEGY_NOTIONAL:
        return "risk_or_size_refused"
    if not _eligible_sessions(signal, execution, now.astimezone(_NY).date()):
        return "ineligible_session"
    return None


def _eligible_sessions(signal: date, execution: date, today: date) -> bool:
    if execution != today:
        return False
    month = sessions_between(
        date(signal.year, signal.month, 1), date(signal.year, signal.month, 10)
    )
    if not month or signal != month[0]:
        return False
    return execution == signal or execution == next_session(signal)


def _send(
    settings: Settings,
    client: Any,
    client_order_id: str,
    symbol: str,
    side: str,
    notional: Decimal,
) -> dict[str, Any]:
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import MarketOrderRequest

    request = MarketOrderRequest(
        symbol=symbol,
        notional=notional,
        side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
        client_order_id=client_order_id,
    )
    try:
        client.submit_order(request)
    except Exception:  # noqa: BLE001 — acceptance is decided by the broker record
        pass
    return _confirm_broker_record(settings, client, client_order_id)


def _confirm_broker_record(settings: Settings, client: Any, client_order_id: str) -> dict[str, Any]:
    local = _find(settings.paper_path, client_order_id)
    try:
        found = client.get_order_by_client_id(client_order_id)
    except Exception:  # noqa: BLE001
        _update(settings.paper_path, client_order_id, broker_status="unknown")
        return _unknown(client_order_id)
    if found is None:
        _update(settings.paper_path, client_order_id, broker_status="unknown")
        return _unknown(client_order_id)
    mapped = _map_status(str(getattr(found, "status", "unknown")))
    filled_qty = _money(getattr(found, "filled_qty", None))
    order_qty = _money(getattr(found, "qty", None))
    price = _money(getattr(found, "filled_avg_price", None))
    if local and local.get("filled_qty") and filled_qty is not None:
        if Decimal(str(local["filled_qty"])) != filled_qty:
            _update(settings.paper_path, client_order_id, broker_status="unknown")
            return _refused("ledger_disagreement")
    remaining = None if order_qty is None or filled_qty is None else order_qty - filled_qty
    _update(
        settings.paper_path,
        client_order_id,
        broker_status=mapped,
        broker_order_id=str(getattr(found, "id", "") or ""),
        filled_avg_price=None if price is None else format(price, "f"),
        filled_qty=None if filled_qty is None else format(filled_qty, "f"),
        remaining_qty=None if remaining is None else format(remaining, "f"),
    )
    return {
        "submitted": mapped not in _RELEASED,
        "status": mapped,
        "client_order_id": client_order_id,
        "filled_qty": None if filled_qty is None else format(filled_qty, "f"),
        "remaining_qty": None if remaining is None else format(remaining, "f"),
        "filled_avg_price": None if price is None else format(price, "f"),
        "label": CONNECTIVITY_LABEL if client_order_id == CONNECTIVITY_CLIENT_ID else LABEL,
        "counts_as_strategy_pnl": bool(local and local.get("counts_as_strategy_pnl")),
        "described_as_filled": mapped == "filled",
    }


def _map_status(status: str) -> str:
    normalized = status.lower()
    if normalized == "partially_filled":
        return "partial"
    if normalized == "filled":
        return "filled"
    if normalized in _OPEN or normalized in _RELEASED:
        return normalized
    return "unknown"


def _exposure(orders: list[dict[str, Any]]) -> dict[str, Any]:
    capital = Decimal("0")
    qty: dict[str, Decimal] = {}
    for row in orders:
        status = str(row["broker_status"])
        side = str(row["side"])
        symbol = str(row["symbol"])
        notional = Decimal(str(row["notional_usd"]))
        filled_qty = _money(row.get("filled_qty")) or Decimal("0")
        price = _money(row.get("filled_avg_price"))
        if side == "buy":
            capital += _buy_capital(status, notional, filled_qty, price)
            if status in {"filled", "partial"} or (status in _RELEASED and filled_qty > 0):
                qty[symbol] = qty.get(symbol, Decimal("0")) + filled_qty
        elif (
            side == "sell"
            and status in {"filled", "partial"}
            and filled_qty > 0
            and price is not None
        ):
            capital -= filled_qty * price
            qty[symbol] = qty.get(symbol, Decimal("0")) - filled_qty
    if capital < 0:
        capital = Decimal("0")
    return {"capital": capital, "qty": qty}


def _open_sell_notional(orders: list[dict[str, Any]], symbol: str) -> Decimal:
    reserved = Decimal("0")
    for row in orders:
        if str(row["symbol"]) != symbol or str(row["side"]) != "sell":
            continue
        status = str(row["broker_status"])
        notional = Decimal(str(row["notional_usd"]))
        filled_qty = _money(row.get("filled_qty")) or Decimal("0")
        price = _money(row.get("filled_avg_price"))
        if status == "partial" and price is not None:
            reserved += max(Decimal("0"), notional - filled_qty * price)
        elif status in _OPEN:
            reserved += notional
    return reserved


def _buy_capital(
    status: str, notional: Decimal, filled_qty: Decimal, price: Decimal | None
) -> Decimal:
    if status in _RELEASED and filled_qty <= 0:
        return Decimal("0")
    if status == "filled" and price is not None and filled_qty > 0:
        return filled_qty * price
    if status == "partial" and price is not None and filled_qty > 0:
        return filled_qty * price + max(Decimal("0"), notional - filled_qty * price)
    if status in _RELEASED and price is not None and filled_qty > 0:
        return filled_qty * price
    return notional


def _sleeve(cash: Decimal, buying_power: Decimal, used: Decimal) -> dict[str, Any]:
    if cash < 0 or buying_power < 0 or used < 0:
        return {"blocked": True, "remaining": Decimal("0"), "reason": "unreliable_amounts"}
    remaining = min(CEILING, cash) - used
    if remaining <= 0:
        return {"blocked": True, "remaining": Decimal("0"), "reason": "sleeve_exhausted"}
    return {"blocked": False, "remaining": remaining, "reason": None}


def _order_filter() -> Any:
    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest

    return GetOrdersRequest(status=QueryOrderStatus.ALL, limit=50)


def _listed_orders(client: Any) -> list[Any] | None:
    try:
        return list(client.get_orders(_order_filter()))
    except Exception:  # noqa: BLE001 — broker text can contain secrets
        return None


def _untracked(local: list[dict[str, Any]], broker: list[Any]) -> bool:
    known = {str(row["client_order_id"]) for row in local}
    for order in broker:
        client_order_id = str(getattr(order, "client_order_id", "") or "")
        if client_order_id not in known:
            return True
    return False


def _public_broker_order(item: Any) -> dict[str, str]:
    return {
        "id": str(getattr(item, "id", "")),
        "client_order_id": str(getattr(item, "client_order_id", "") or ""),
        "symbol": str(getattr(item, "symbol", "")),
        "side": str(getattr(item, "side", "")),
        "status": str(getattr(item, "status", "")),
        "notional": str(getattr(item, "notional", "") or ""),
        "filled_qty": str(getattr(item, "filled_qty", "") or ""),
        "filled_avg_price": str(getattr(item, "filled_avg_price", "") or ""),
    }


def _broker_qty(client: Any, symbol: str) -> Decimal | None:
    try:
        positions = list(client.get_all_positions())
    except Exception:  # noqa: BLE001
        return None
    for item in positions:
        if str(getattr(item, "symbol", "")).upper() != symbol:
            continue
        side = str(getattr(item, "side", "")).lower()
        qty = _money(getattr(item, "qty", None))
        if "short" in side or (qty is not None and qty < 0):
            return None
        return qty
    return Decimal("0")


def _reconcile(settings: Settings, client: Any, orders: list[dict[str, Any]]) -> bool:
    disagreed = False
    for row in orders:
        if row["broker_status"] in {"prepared", *_RELEASED}:
            continue
        before = row.get("filled_qty")
        result = _confirm_broker_record(settings, client, str(row["client_order_id"]))
        if result.get("reason") == "ledger_disagreement":
            disagreed = True
        elif (
            before
            and result.get("filled_qty")
            and Decimal(str(before)) != Decimal(str(result["filled_qty"]))
        ):
            disagreed = True
    return disagreed


def _client(settings: Settings) -> Any | None:
    if not settings.credentials_configured or settings.alpaca_base_url != PAPER_API_URL:
        return None
    key = settings.alpaca_api_key
    secret = settings.alpaca_api_secret
    if key is None or secret is None:
        return None
    from alpaca.trading.client import TradingClient

    return TradingClient(
        key.get_secret_value(),
        secret.get_secret_value(),
        paper=True,
        url_override=PAPER_API_URL,
    )


def _base(clock: datetime) -> dict[str, Any]:
    return {
        "label": LABEL,
        "as_of": clock.isoformat(),
        "paper_url": PAPER_API_URL,
        "live_trading": False,
        "allow_order_submission": False,
        "historical_replay_counts_as_performance": False,
        "execution_model": "alpaca_paper_market_order",
        "internal_hypothetical_fills": "not_authoritative",
    }


def _authorization(path: str, now: datetime) -> dict[str, Any]:
    row = _control(path)
    if row.get("status") == "corrupt":
        return {"enabled": False, "reason": "ledger_unreadable"}
    if row.get("status") == "killed":
        return {"enabled": False, "reason": "killed"}
    if row.get("status") != "enabled" or not row.get("expires_at"):
        return {"enabled": False, "reason": "paper_orders_disabled"}
    expires = datetime.fromisoformat(str(row["expires_at"]))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires <= now:
        return {"enabled": False, "reason": "authorization_expired"}
    return {"enabled": True, "reason": None, "expires_at": expires.isoformat()}


def _automatic(path: str, now: datetime) -> dict[str, Any]:
    file = Path(path)
    if not file.is_file():
        return {"enabled": False, "reason": "automatic_pilot_disabled"}
    try:
        with sqlite3.connect(file) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM paper_automatic WHERE id = 1").fetchone()
    except sqlite3.DatabaseError:
        return {"enabled": False, "reason": "ledger_unreadable"}
    if row is None or row["status"] != "enabled" or not row["expires_at"]:
        return {"enabled": False, "reason": "automatic_pilot_disabled"}
    expires = datetime.fromisoformat(str(row["expires_at"]))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires <= now:
        return {"enabled": False, "reason": "authorization_expired"}
    return {"enabled": True, "reason": None, "expires_at": expires.isoformat()}


def _public_order(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "client_order_id": row["client_order_id"],
        "purpose": row["purpose"],
        "symbol": row["symbol"],
        "side": row["side"],
        "notional_usd": row["notional_usd"],
        "broker_status": row["broker_status"],
        "filled_qty": row.get("filled_qty"),
        "remaining_qty": row.get("remaining_qty"),
        "filled_avg_price": row.get("filled_avg_price"),
        "counts_as_strategy_pnl": bool(row["counts_as_strategy_pnl"]),
        "label": CONNECTIVITY_LABEL if row["purpose"] == "connectivity" else LABEL,
    }


def _position(item: Any) -> dict[str, str]:
    return {
        "symbol": str(getattr(item, "symbol", "")),
        "qty": str(getattr(item, "qty", "")),
        "side": str(getattr(item, "side", "")),
        "market_value": str(getattr(item, "market_value", "")),
        "unrealized_pl": str(getattr(item, "unrealized_pl", "")),
    }


def _orders(path: str) -> list[dict[str, Any]]:
    file = Path(path)
    if not file.is_file():
        return []
    with sqlite3.connect(file) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM paper_orders ORDER BY created_at").fetchall()
    return [dict(row) for row in rows]


def _orders_safe(path: str) -> list[dict[str, Any]]:
    try:
        return _orders(path)
    except sqlite3.DatabaseError:
        return []


def _find(path: str, client_order_id: str) -> dict[str, Any] | None:
    for row in _orders(path):
        if row["client_order_id"] == client_order_id:
            return row
    return None


def _control(path: str) -> dict[str, Any]:
    file = Path(path)
    if not file.is_file():
        return {"status": "disabled"}
    try:
        with sqlite3.connect(file) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM paper_control WHERE id = 1").fetchone()
    except sqlite3.DatabaseError:
        return {"status": "corrupt"}
    return {} if row is None else dict(row)


def _connect(path: str) -> sqlite3.Connection:
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(file)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(paper_orders)")}
    for name in ("remaining_qty", "decision_id"):
        if name not in columns:
            conn.execute(f"ALTER TABLE paper_orders ADD COLUMN {name} TEXT")
    return conn


def _write_control(path: str, **fields: object) -> None:
    with _connect(path) as conn:
        conn.execute(
            """
            INSERT INTO paper_control (id, status, enabled_at, expires_at, killed_at)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                enabled_at = excluded.enabled_at,
                expires_at = excluded.expires_at,
                killed_at = excluded.killed_at
            """,
            (fields["status"], fields["enabled_at"], fields["expires_at"], fields["killed_at"]),
        )


def _write_automatic(path: str, **fields: object) -> None:
    with _connect(path) as conn:
        conn.execute(
            """
            INSERT INTO paper_automatic (id, status, expires_at, killed_at)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                expires_at = excluded.expires_at,
                killed_at = excluded.killed_at
            """,
            (fields["status"], fields["expires_at"], fields["killed_at"]),
        )


def _insert_order(path: str, **fields: object) -> None:
    with _connect(path) as conn:
        conn.execute(
            """
            INSERT INTO paper_orders (
                client_order_id, purpose, symbol, side, notional_usd, created_at,
                broker_status, decision_id, counts_as_strategy_pnl
            ) VALUES (?, ?, ?, ?, ?, ?, 'prepared', ?, ?)
            """,
            (
                fields["client_order_id"],
                fields["purpose"],
                fields["symbol"],
                fields["side"],
                format(fields["notional"], "f"),
                fields["created_at"],
                fields["decision_id"],
                1 if fields["counts_as_strategy_pnl"] else 0,
            ),
        )


def _update(path: str, client_order_id: str, **fields: object) -> None:
    chosen = [(key, value) for key, value in fields.items() if key in _COLUMNS]
    if not chosen:
        return
    assignments = ", ".join(f"{key} = ?" for key, _value in chosen)
    with _connect(path) as conn:
        conn.execute(
            f"UPDATE paper_orders SET {assignments} WHERE client_order_id = ?",
            [value for _key, value in chosen] + [client_order_id],
        )


def _money(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite():
        return None
    return amount


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _stamp(value: object) -> str | None:
    parsed = _as_datetime(value)
    return None if parsed is None else parsed.isoformat()


def _unknown(client_order_id: str) -> dict[str, Any]:
    return {
        "submitted": False,
        "status": "unknown",
        "client_order_id": client_order_id,
        "filled_qty": None,
        "remaining_qty": None,
        "filled_avg_price": None,
        "reason": "broker_record_not_confirmed",
        "label": LABEL,
        "described_as_filled": False,
    }


def _refused(reason: str) -> dict[str, Any]:
    return {
        "submitted": False,
        "status": "refused",
        "reason": reason,
        "filled_avg_price": None,
        "filled_qty": None,
        "label": LABEL,
        "broker_orders": False,
        "described_as_filled": False,
    }


def redact(report: dict[str, Any]) -> str:
    """JSON for a readiness file. Caller must not add credentials."""
    return json.dumps(report, indent=2, default=str)
