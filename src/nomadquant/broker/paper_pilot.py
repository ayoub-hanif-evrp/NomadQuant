"""Alpaca paper orders against the current market. Fake money only.

Live trading endpoints are refused. Submission stays off until an unexpired
local authorization exists. Historical replay is not a fill and is not P&L.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from nomadquant.config import PAPER_API_URL, Settings
from nomadquant.risk.policy import ALLOWED_SYMBOLS

LABEL = "ALPACA PAPER TRADING — FAKE MONEY"
CEILING = Decimal("100")
CONNECTIVITY_CAP = Decimal("5")
ENABLE_PHRASE = "ENABLE_ALPACA_PAPER_ORDERS"
KILL_PHRASE = "DISABLE_ALPACA_PAPER_ORDERS"
CONNECTIVITY_PHRASE = "SUBMIT_ONE_FIVE_DOLLAR_PAPER_CONNECTIVITY_ORDER"
MAX_ENABLE = timedelta(hours=24)
_OPEN = frozenset({"prepared", "submitted", "unknown", "accepted", "partial", "pending_new", "new"})
_RELEASED = frozenset({"canceled", "cancelled", "rejected", "expired"})

SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_control (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    status TEXT NOT NULL,
    enabled_at TEXT,
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
    counts_as_strategy_pnl INTEGER NOT NULL
);
"""


def paper_status(
    settings: Settings, *, client: Any | None = None, now: datetime | None = None
) -> dict[str, Any]:
    """Read the paper account, clock, and SPY asset. Does not submit an order."""
    clock = now or datetime.now(UTC)
    base = _base(clock)
    if settings.alpaca_base_url != PAPER_API_URL:
        return {**base, "connected": False, "blocked": True, "reason": "non_paper_url"}
    trading = client if client is not None else _client(settings)
    if trading is None:
        return {**base, "connected": False, "blocked": True, "reason": "credentials_absent"}
    try:
        account = trading.get_account()
        market = trading.get_clock()
        asset = trading.get_asset("SPY")
        positions = list(trading.get_all_positions())
    except Exception as exc:  # noqa: BLE001 — broker text can contain secrets
        return {**base, "connected": False, "blocked": True, "reason": type(exc).__name__}
    cash = _decimal(getattr(account, "cash", None))
    equity = _decimal(getattr(account, "equity", None))
    buying_power = _decimal(getattr(account, "buying_power", None))
    if cash is None or equity is None or buying_power is None:
        return {**base, "connected": False, "blocked": True, "reason": "account_amounts_unreadable"}
    orders = _orders(settings.paper_path)
    spent = _reserved(orders)
    sleeve = _sleeve(cash, buying_power, spent)
    fractionable = bool(getattr(asset, "fractionable", False))
    tradable = bool(getattr(asset, "tradable", False))
    reconciled = _reconcile(settings, trading, orders)
    return {
        **base,
        "connected": True,
        "blocked": sleeve["blocked"] or not fractionable or not tradable,
        "reason": None if not sleeve["blocked"] else sleeve["reason"],
        "market_open": bool(getattr(market, "is_open", False)),
        "market_timestamp": _stamp(getattr(market, "timestamp", None)),
        "feed": "alpaca_paper",
        "account_cash_usd": str(cash),
        "account_equity_usd": str(equity),
        "account_buying_power_usd": str(buying_power),
        "buying_power_ignored": True,
        "sleeve_usd": "100",
        "sleeve_remaining_usd": str(sleeve["remaining"]),
        "spy_fractionable": fractionable,
        "spy_tradable": tradable,
        "positions": [_position(item) for item in positions],
        "orders": reconciled,
        "strategy_pnl": "not_started",
        "authorization": _authorization(settings.paper_path, clock),
        "submission_enabled": bool(_authorization(settings.paper_path, clock)["enabled"]),
        "ready_for_first_order": bool(
            sleeve["remaining"] >= CONNECTIVITY_CAP
            and fractionable
            and tradable
            and bool(getattr(market, "is_open", False))
            and _authorization(settings.paper_path, clock)["enabled"]
        ),
        "first_order_authorization": (
            "Say to enable paper orders for at most 24 hours with "
            f"{ENABLE_PHRASE}, then separately authorize one connectivity "
            f"order with {CONNECTIVITY_PHRASE}. No order is sent until then."
        ),
    }


def enable_paper_orders(
    settings: Settings, *, confirm: str, hours: int, now: datetime | None = None
) -> dict[str, Any]:
    """Arm the paper switch. This does not submit an order."""
    clock = now or datetime.now(UTC)
    if confirm != ENABLE_PHRASE:
        raise ValueError("Paper orders stay disabled without the exact enable phrase.")
    if hours < 1 or hours > 24:
        raise ValueError("Paper authorization must expire within 24 hours.")
    if settings.alpaca_base_url != PAPER_API_URL or settings.allow_order_submission:
        raise ValueError("Paper authorization refuses a live endpoint or the live order flag.")
    _write_control(
        settings.paper_path,
        status="enabled",
        enabled_at=clock.isoformat(),
        expires_at=(clock + timedelta(hours=hours)).isoformat(),
        killed_at=None,
    )
    return {
        "enabled": True,
        "expires_at": (clock + timedelta(hours=hours)).isoformat(),
        "orders_sent": 0,
    }


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
    return {"enabled": False, "killed": True}


def submit_connectivity_order(
    settings: Settings,
    *,
    confirm: str,
    client: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    """One Alpaca paper buy of at most $5. Refuses unless separately authorized."""
    clock = now or datetime.now(UTC)
    if confirm != CONNECTIVITY_PHRASE:
        return _refused("authorization_missing")
    auth = _authorization(settings.paper_path, clock)
    if not auth["enabled"]:
        return _refused(str(auth["reason"]))
    if settings.alpaca_base_url != PAPER_API_URL:
        return _refused("non_paper_url")
    existing = [
        row
        for row in _orders(settings.paper_path)
        if row["purpose"] == "connectivity" and row["broker_status"] not in _RELEASED
    ]
    if existing:
        return _refused("connectivity_order_already_exists")
    try:
        market = client.get_clock()
        asset = client.get_asset("SPY")
        account = client.get_account()
    except Exception as exc:  # noqa: BLE001
        return _refused(f"broker_unread:{type(exc).__name__}")
    if (
        not bool(getattr(market, "is_open", False))
        or _stamp(getattr(market, "timestamp", None)) is None
    ):
        return _refused("market_not_open")
    if not bool(getattr(asset, "fractionable", False)) or not bool(
        getattr(asset, "tradable", False)
    ):
        return _refused("spy_not_fractionable")
    cash = _decimal(getattr(account, "cash", None))
    buying_power = _decimal(getattr(account, "buying_power", None))
    if cash is None or buying_power is None:
        return _refused("account_amounts_unreadable")
    notional = CONNECTIVITY_CAP
    remaining = _sleeve(cash, buying_power, _reserved(_orders(settings.paper_path)))["remaining"]
    if notional > remaining or notional > CONNECTIVITY_CAP:
        return _refused("sleeve_exceeded")
    client_order_id = f"nq-connect-{uuid.uuid4().hex}"
    _insert_order(
        settings.paper_path,
        client_order_id=client_order_id,
        purpose="connectivity",
        symbol="SPY",
        side="buy",
        notional=notional,
        created_at=clock.isoformat(),
        broker_status="prepared",
        counts_as_strategy_pnl=False,
    )
    return _send(settings, client, client_order_id, "SPY", "buy", notional)


def submit_strategy_paper_order(
    settings: Settings,
    *,
    symbol: str,
    side: str,
    notional: Decimal,
    risk_verdict: str,
    client: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    """A registered-strategy paper order. Disabled unless the paper switch is on."""
    clock = now or datetime.now(UTC)
    auth = _authorization(settings.paper_path, clock)
    if not auth["enabled"]:
        return _refused(str(auth["reason"]))
    if symbol not in ALLOWED_SYMBOLS or side != "buy" and side != "sell":
        return _refused("symbol_or_side_refused")
    if side == "sell" and _flat(client, symbol):
        return _refused("short_selling_refused")
    return _strategy_send(settings, client, symbol, side, notional, risk_verdict, clock)


def _strategy_send(
    settings: Settings,
    client: Any,
    symbol: str,
    side: str,
    notional: Decimal,
    risk_verdict: str,
    clock: datetime,
) -> dict[str, Any]:
    if risk_verdict != "APPROVE" or notional <= 0 or notional > Decimal("50"):
        return _refused("risk_or_size_refused")
    if settings.alpaca_base_url != PAPER_API_URL:
        return _refused("non_paper_url")
    cash = _decimal(getattr(client.get_account(), "cash", None))
    buying_power = _decimal(getattr(client.get_account(), "buying_power", None))
    if cash is None or buying_power is None:
        return _refused("account_amounts_unreadable")
    remaining = _sleeve(cash, buying_power, _reserved(_orders(settings.paper_path)))["remaining"]
    if notional > remaining:
        return _refused("sleeve_exceeded")
    client_order_id = f"nq-strategy-{uuid.uuid4().hex}"
    _insert_order(
        settings.paper_path,
        client_order_id=client_order_id,
        purpose="strategy",
        symbol=symbol,
        side=side,
        notional=notional,
        created_at=clock.isoformat(),
        broker_status="prepared",
        counts_as_strategy_pnl=True,
    )
    return _send(settings, client, client_order_id, symbol, side, notional)


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
    except Exception as exc:  # noqa: BLE001
        if not _timeout(exc):
            _update(settings.paper_path, client_order_id, broker_status="rejected")
            return _refused(f"broker_rejected:{type(exc).__name__}")
    return _confirm_broker_record(settings, client, client_order_id)


def _confirm_broker_record(settings: Settings, client: Any, client_order_id: str) -> dict[str, Any]:
    try:
        found = client.get_order_by_client_id(client_order_id)
    except Exception:  # noqa: BLE001
        _update(settings.paper_path, client_order_id, broker_status="unknown")
        return {
            "submitted": False,
            "status": "unknown",
            "client_order_id": client_order_id,
            "filled_avg_price": None,
            "reason": "broker_record_not_confirmed",
            "label": LABEL,
        }
    status = str(getattr(found, "status", "unknown")).lower()
    price = getattr(found, "filled_avg_price", None)
    qty = getattr(found, "filled_qty", None)
    mapped = "filled" if status in {"filled", "partially_filled"} else status or "unknown"
    if mapped == "partially_filled":
        mapped = "partial"
    _update(
        settings.paper_path,
        client_order_id,
        broker_status=mapped if mapped in _OPEN | _RELEASED | {"filled"} else "unknown",
        broker_order_id=str(getattr(found, "id", "") or ""),
        filled_avg_price=None if price in (None, "") else str(price),
        filled_qty=None if qty in (None, "") else str(qty),
    )
    return {
        "submitted": True,
        "status": mapped,
        "client_order_id": client_order_id,
        "filled_avg_price": None if price in (None, "") else str(price),
        "label": LABEL,
        "counts_as_strategy_pnl": client_order_id.startswith("nq-strategy-"),
    }


def _sleeve(cash: Decimal, buying_power: Decimal, reserved: Decimal) -> dict[str, Any]:
    if cash < 0 or buying_power < 0 or reserved < 0:
        return {"blocked": True, "remaining": Decimal("0"), "reason": "unreliable_amounts"}
    remaining = min(CEILING, cash) - reserved
    if remaining <= 0:
        return {"blocked": True, "remaining": Decimal("0"), "reason": "sleeve_exhausted"}
    return {"blocked": False, "remaining": remaining, "reason": None}


def _flat(client: Any, symbol: str) -> bool:
    try:
        positions = list(client.get_all_positions())
    except Exception:  # noqa: BLE001
        return True
    for item in positions:
        if str(getattr(item, "symbol", "")).upper() == symbol and _decimal(
            getattr(item, "qty", None)
        ):
            qty = _decimal(getattr(item, "qty", None))
            if qty is not None and qty > 0:
                return False
    return True


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


def _reserved(orders: list[dict[str, Any]]) -> Decimal:
    total = Decimal("0")
    for row in orders:
        if str(row["broker_status"]) in _RELEASED:
            continue
        if (
            str(row["broker_status"]) == "filled"
            and row.get("filled_avg_price")
            and row.get("filled_qty")
        ):
            total += Decimal(str(row["filled_qty"])) * Decimal(str(row["filled_avg_price"]))
        else:
            total += Decimal(str(row["notional_usd"]))
    return total


def _reconcile(
    settings: Settings, client: Any, orders: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    updated: list[dict[str, Any]] = []
    for row in orders:
        current = row
        if row["broker_status"] in _OPEN and row["broker_status"] != "prepared":
            confirmed = _confirm_broker_record(settings, client, str(row["client_order_id"]))
            current = {
                **row,
                "broker_status": confirmed["status"],
                "filled_avg_price": confirmed.get("filled_avg_price"),
            }
        updated.append(_public_order(current))
    return updated


def _public_order(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "client_order_id": row["client_order_id"],
        "purpose": row["purpose"],
        "symbol": row["symbol"],
        "side": row["side"],
        "notional_usd": row["notional_usd"],
        "broker_status": row["broker_status"],
        "filled_avg_price": row.get("filled_avg_price"),
        "counts_as_strategy_pnl": bool(row["counts_as_strategy_pnl"]),
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


def _control(path: str) -> dict[str, Any]:
    file = Path(path)
    if not file.is_file():
        return {"status": "disabled"}
    with sqlite3.connect(file) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM paper_control WHERE id = 1").fetchone()
    return {} if row is None else dict(row)


def _connect(path: str) -> sqlite3.Connection:
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(file)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
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


def _insert_order(path: str, **fields: object) -> None:
    with _connect(path) as conn:
        conn.execute(
            """
            INSERT INTO paper_orders (
                client_order_id, purpose, symbol, side, notional_usd, created_at,
                broker_status, counts_as_strategy_pnl
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fields["client_order_id"],
                fields["purpose"],
                fields["symbol"],
                fields["side"],
                format(fields["notional"], "f"),
                fields["created_at"],
                fields["broker_status"],
                1 if fields["counts_as_strategy_pnl"] else 0,
            ),
        )


def _update(path: str, client_order_id: str, **fields: object) -> None:
    assignments = []
    values: list[object] = []
    for key, value in fields.items():
        if value is None and key != "filled_avg_price":
            continue
        assignments.append(f"{key} = ?")
        values.append(value)
    if not assignments:
        return
    values.append(client_order_id)
    with _connect(path) as conn:
        conn.execute(
            f"UPDATE paper_orders SET {', '.join(assignments)} WHERE client_order_id = ?",
            values,
        )


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount


def _stamp(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        stamped = value if value.tzinfo else value.replace(tzinfo=UTC)
        return stamped.isoformat()
    text = str(value).strip()
    return text or None


def _timeout(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    return "timeout" in name or isinstance(exc, TimeoutError)


def _refused(reason: str) -> dict[str, Any]:
    return {
        "submitted": False,
        "status": "refused",
        "reason": reason,
        "filled_avg_price": None,
        "label": LABEL,
        "broker_orders": False,
    }


def redact(report: dict[str, Any]) -> str:
    """JSON for a readiness file. Caller must not add credentials."""
    return json.dumps(report, indent=2, default=str)
