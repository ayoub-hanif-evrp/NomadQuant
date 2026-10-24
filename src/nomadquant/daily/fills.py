"""Append-only paper executions. Order creation time is not a fill time."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

_PAGE_SIZE = 100
_MAX_PAGES = 20

_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_executions (
    execution_id TEXT PRIMARY KEY,
    client_order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty TEXT NOT NULL,
    price TEXT NOT NULL,
    executed_at TEXT,
    purpose TEXT NOT NULL,
    aggregate INTEGER NOT NULL,
    recorded_at TEXT NOT NULL
);
"""


def record_execution(path: str, execution: dict[str, Any], *, recorded_at: str) -> str:
    """Insert one fill. The same id and economics return ``duplicate``.

    A repeated id with different economics returns ``conflict`` and writes nothing.
    """
    execution_id = str(execution.get("execution_id") or "")
    if not execution_id:
        return "conflict"
    row = _normalized(execution)
    if row is None:
        return "conflict"
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(file) as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript(_SCHEMA)
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT * FROM paper_executions WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
        if existing is not None:
            return "duplicate" if _same(existing, row) else "conflict"
        connection.execute(
            """
            INSERT INTO paper_executions (
                execution_id, client_order_id, symbol, side, qty, price,
                executed_at, purpose, aggregate, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                execution_id,
                row["client_order_id"],
                row["symbol"],
                row["side"],
                row["qty"],
                row["price"],
                row["executed_at"],
                row["purpose"],
                1 if row["aggregate"] else 0,
                recorded_at,
            ),
        )
    return "recorded"


def collect_fill_pages(
    fetch_page: Any,
    *,
    page_size: int = _PAGE_SIZE,
    max_pages: int = _MAX_PAGES,
) -> list[Any] | None:
    """Read every page. A failed, repeated, or unfinished page is incomplete."""
    found: list[Any] = []
    token: str | None = None
    seen: set[str] = set()
    for _ in range(max_pages):
        page = fetch_page(token)
        if not isinstance(page, list):
            return None
        found.extend(page)
        if len(page) < page_size:
            return found
        last = str(_field(page[-1], "id") or "")
        if not last or last in seen:
            return None
        seen.add(last)
        token = last
    return None


def record_executions(path: str, executions: list[dict[str, Any]], *, recorded_at: str) -> str:
    """Insert a batch in one transaction. A conflict writes nothing new."""
    pending: list[tuple[str, dict[str, Any]]] = []
    for execution in executions:
        execution_id = str(execution.get("execution_id") or "")
        row = _normalized(execution)
        if not execution_id or row is None:
            return "conflict"
        pending.append((execution_id, row))
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(file) as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript(_SCHEMA)
        connection.execute("BEGIN IMMEDIATE")
        for execution_id, row in pending:
            existing = connection.execute(
                "SELECT * FROM paper_executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            if existing is not None:
                if not _same(existing, row):
                    connection.rollback()
                    return "conflict"
                continue
            connection.execute(
                """
                INSERT INTO paper_executions (
                    execution_id, client_order_id, symbol, side, qty, price,
                    executed_at, purpose, aggregate, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    execution_id,
                    row["client_order_id"],
                    row["symbol"],
                    row["side"],
                    row["qty"],
                    row["price"],
                    row["executed_at"],
                    row["purpose"],
                    1 if row["aggregate"] else 0,
                    recorded_at,
                ),
            )
    return "recorded"


def load_executions(path: str) -> list[dict[str, Any]]:
    file = Path(path)
    if not file.exists():
        return []
    with sqlite3.connect(file) as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript(_SCHEMA)
        rows = connection.execute(
            "SELECT * FROM paper_executions ORDER BY recorded_at, execution_id"
        ).fetchall()
    return [_public(row) for row in rows]


def execution_from_activity(
    activity: Any, *, client_order_id: str, purpose: str
) -> dict[str, Any] | None:
    """Map one Alpaca FILL activity. A missing id or timestamp is not a fill."""
    execution_id = str(_field(activity, "id") or "")
    kind = str(_field(activity, "activity_type") or "FILL").upper()
    if not execution_id or kind != "FILL":
        return None
    return _event(
        execution_id=execution_id,
        client_order_id=client_order_id,
        symbol=str(_field(activity, "symbol") or ""),
        side=str(_field(activity, "side") or ""),
        qty=_field(activity, "qty"),
        price=_field(activity, "price"),
        executed_at=_field(activity, "transaction_time"),
        purpose=purpose,
        aggregate=False,
    )


def execution_from_trade_update(event: Any, *, purpose: str) -> dict[str, Any] | None:
    """Map one ``trade_updates`` fill. No stable execution id means no journal row."""
    body = event.get("data", event) if isinstance(event, dict) else event
    name = str(_field(body, "event") or "")
    if name not in {"fill", "partial_fill"}:
        return None
    execution_id = str(_field(body, "execution_id") or "")
    order = _field(body, "order")
    if not execution_id or order is None:
        return None
    return _event(
        execution_id=execution_id,
        client_order_id=str(_field(order, "client_order_id") or ""),
        symbol=str(_field(order, "symbol") or ""),
        side=str(_field(order, "side") or ""),
        qty=_field(body, "qty"),
        price=_field(body, "price"),
        executed_at=_field(body, "timestamp"),
        purpose=purpose,
        aggregate=False,
    )


def journal_broker_order(
    path: str,
    local: dict[str, Any] | None,
    broker_order: Any,
    activities: list[Any] | None,
    *,
    recorded_at: str,
    activity_state: str = "unavailable",
) -> str:
    """Store broker fills for one order.

    ``complete`` means every page for that broker order was read. Those rows are
    written only when the symbol, side, quantity, and average price agree.
    ``incomplete`` is never stored as a finished history. ``unavailable`` may
    store one aggregate estimate, which is not a session fill.
    """
    if local is None:
        return "ok"
    broker_id = str(getattr(broker_order, "id", "") or "")
    if not broker_id:
        return "unverified"
    client_order_id = str(local.get("client_order_id") or "")
    purpose = str(local.get("purpose") or "")
    symbol = str(local.get("symbol") or "").upper()
    side = str(local.get("side") or "").lower()
    if activity_state == "incomplete":
        return "unverified"
    if activity_state == "complete":
        detailed: list[dict[str, Any]] = []
        for activity in activities or []:
            if str(_field(activity, "order_id") or "") != broker_id:
                continue
            parsed = execution_from_activity(
                activity, client_order_id=client_order_id, purpose=purpose
            )
            if (
                parsed is None
                or parsed["symbol"] != symbol
                or parsed["side"] != side
                or parsed["purpose"] != purpose
                or parsed.get("executed_at") is None
            ):
                return "unverified"
            detailed.append(parsed)
        filled = _money(getattr(broker_order, "filled_qty", None)) or Decimal("0")
        if not detailed:
            return "ok" if filled == 0 else "unverified"
        average = _money(getattr(broker_order, "filled_avg_price", None))
        if not _totals_match(detailed, filled, average):
            return "unverified"
        state = record_executions(path, detailed, recorded_at=recorded_at)
        return "ok" if state == "recorded" else "conflict"
    return _journal_aggregate(
        path,
        local,
        broker_order,
        broker_id=broker_id,
        client_order_id=client_order_id,
        purpose=purpose,
        recorded_at=recorded_at,
    )


def _journal_aggregate(
    path: str,
    local: dict[str, Any],
    broker_order: Any,
    *,
    broker_id: str,
    client_order_id: str,
    purpose: str,
    recorded_at: str,
) -> str:
    status = str(getattr(broker_order, "status", "") or "").lower().rsplit(".", 1)[-1]
    filled_at = getattr(broker_order, "filled_at", None)
    if status != "filled" or filled_at is None:
        return "unverified"
    aggregate = _event(
        execution_id=f"alpaca-order:{broker_id}:complete",
        client_order_id=client_order_id,
        symbol=str(getattr(broker_order, "symbol", "") or local.get("symbol") or ""),
        side=str(getattr(broker_order, "side", "") or local.get("side") or ""),
        qty=getattr(broker_order, "filled_qty", None),
        price=getattr(broker_order, "filled_avg_price", None),
        executed_at=filled_at,
        purpose=purpose,
        aggregate=True,
    )
    if aggregate is None or aggregate["symbol"] != str(local.get("symbol") or "").upper():
        return "unverified"
    if aggregate["side"] != str(local.get("side") or "").lower():
        return "unverified"
    state = record_execution(path, aggregate, recorded_at=recorded_at)
    return "conflict" if state == "conflict" else "ok"


def _totals_match(lots: list[dict[str, Any]], filled: Decimal, average: Decimal | None) -> bool:
    total = sum((lot["qty"] for lot in lots), Decimal("0"))
    if average is None or total != filled or total <= 0:
        return False
    weighted = sum((lot["qty"] * lot["price"] for lot in lots), Decimal("0")) / total
    quantum = _quantum(average)
    return weighted.quantize(quantum) == average.quantize(quantum)


def _quantum(value: Decimal) -> Decimal:
    text = format(value, "f")
    if "." not in text:
        return Decimal("1")
    return Decimal("1").scaleb(-len(text.split(".", 1)[1]))


def fill_lots(
    orders: list[dict[str, Any]], executions: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], bool]:
    """Choose the fills that reconstruct a book.

    A stored row must match its parent order. A mismatch or an unreadable row
    disputes the book and is not replaced with the order total.
    """
    clean, conflict = _unique(executions)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for lot in clean:
        grouped.setdefault(str(lot["client_order_id"]), []).append(lot)
    known = {str(row.get("client_order_id") or "") for row in orders}
    disputed = conflict or any(key not in known for key in grouped)
    chosen: list[dict[str, Any]] = []
    for row in orders:
        client_order_id = str(row.get("client_order_id") or "")
        filled = _money(row.get("filled_qty")) or Decimal("0")
        matches = grouped.get(client_order_id, [])
        if any(not _agrees(lot, row) for lot in matches):
            disputed = True
            continue
        detailed = [lot for lot in matches if not lot["aggregate"]]
        usable = detailed or [lot for lot in matches if lot["aggregate"]]
        if usable:
            total = sum((lot["qty"] for lot in usable), Decimal("0"))
            if total != filled:
                disputed = True
                continue
            chosen.extend(usable)
            continue
        if filled <= 0 or conflict:
            continue
        price = _money(row.get("filled_avg_price"))
        if price is None or price <= 0:
            disputed = True
            continue
        chosen.append(
            {
                "execution_id": f"unverified:{client_order_id}",
                "client_order_id": client_order_id,
                "symbol": str(row.get("symbol") or ""),
                "side": str(row.get("side") or ""),
                "qty": filled,
                "price": price,
                "executed_at": None,
                "purpose": str(row.get("purpose") or ""),
                "aggregate": False,
            }
        )
    chosen.sort(
        key=lambda lot: (
            1 if lot["executed_at"] is None else 0,
            str(lot["executed_at"] or ""),
            0 if lot["side"] == "buy" else 1,
            str(lot["execution_id"]),
        )
    )
    return chosen, disputed


def _normalized(execution: dict[str, Any]) -> dict[str, Any] | None:
    qty = _money(execution.get("qty"))
    price = _money(execution.get("price"))
    side = str(execution.get("side") or "").lower()
    if "buy" in side:
        side = "buy"
    elif "sell" in side:
        side = "sell"
    executed_at = execution.get("executed_at")
    stamp = None if executed_at in {None, ""} else _aware_text(executed_at)
    if (
        qty is None
        or qty <= 0
        or price is None
        or price <= 0
        or side not in {"buy", "sell"}
        or not str(execution.get("client_order_id") or "")
        or not str(execution.get("symbol") or "")
        or executed_at not in {None, ""}
        and stamp is None
    ):
        return None
    return {
        "client_order_id": str(execution["client_order_id"]),
        "symbol": str(execution["symbol"]).upper(),
        "side": side,
        "qty": format(qty, "f"),
        "price": format(price, "f"),
        "executed_at": stamp,
        "purpose": str(execution.get("purpose") or ""),
        "aggregate": bool(execution.get("aggregate")),
    }


def _event(**fields: Any) -> dict[str, Any] | None:
    executed_at = fields["executed_at"]
    if isinstance(executed_at, datetime):
        executed_at = executed_at.isoformat()
    parsed = _normalized(
        {**fields, "executed_at": executed_at, "qty": fields["qty"], "price": fields["price"]}
    )
    if parsed is None:
        return None
    return {
        "execution_id": fields["execution_id"],
        **parsed,
        "qty": _money(parsed["qty"]),
        "price": _money(parsed["price"]),
    }


def _public(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "execution_id": row["execution_id"],
        "client_order_id": row["client_order_id"],
        "symbol": row["symbol"],
        "side": row["side"],
        "qty": Decimal(str(row["qty"])),
        "price": Decimal(str(row["price"])),
        "executed_at": row["executed_at"],
        "purpose": row["purpose"],
        "aggregate": bool(row["aggregate"]),
    }


def _same(existing: sqlite3.Row, row: dict[str, Any]) -> bool:
    checks = (
        existing["client_order_id"] == row["client_order_id"],
        existing["symbol"] == row["symbol"],
        existing["side"] == row["side"],
        existing["qty"] == row["qty"],
        existing["price"] == row["price"],
        existing["executed_at"] == row["executed_at"],
        existing["purpose"] == row["purpose"],
        bool(existing["aggregate"]) == row["aggregate"],
    )
    return bool(all(checks))


def _agrees(lot: dict[str, Any], order: dict[str, Any]) -> bool:
    """A stored fill must name the same order, symbol, side, purpose, and quantity."""
    side = str(order.get("side") or "").lower()
    if "buy" in side:
        side = "buy"
    elif "sell" in side:
        side = "sell"
    qty = lot.get("qty")
    price = lot.get("price")
    stamp = lot.get("executed_at")
    return bool(
        str(lot.get("client_order_id") or "") == str(order.get("client_order_id") or "")
        and str(lot.get("symbol") or "").upper() == str(order.get("symbol") or "").upper()
        and str(lot.get("side") or "") == side
        and str(lot.get("purpose") or "") == str(order.get("purpose") or "")
        and isinstance(qty, Decimal)
        and qty > 0
        and isinstance(price, Decimal)
        and price > 0
        and (stamp in {None, ""} or _aware_text(stamp) is not None)
    )


def _unique(executions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    chosen: dict[str, dict[str, Any]] = {}
    conflict = False
    for raw in executions:
        execution_id = str(raw.get("execution_id") or "")
        row = _normalized(raw)
        if not execution_id or row is None:
            conflict = True
            continue
        item = {
            "execution_id": execution_id,
            **row,
            "qty": _money(row["qty"]),
            "price": _money(row["price"]),
        }
        previous = chosen.get(execution_id)
        if previous is None:
            chosen[execution_id] = item
            continue
        if any(
            previous[key] != item[key] for key in ("qty", "price", "executed_at", "side", "symbol")
        ):
            conflict = True
    return list(chosen.values()), conflict


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _aware_text(value: object) -> str | None:
    if isinstance(value, datetime):
        stamp = value if value.tzinfo is not None else None
    else:
        try:
            stamp = datetime.fromisoformat(str(value))
        except ValueError:
            return None
        if stamp.tzinfo is None:
            return None
    if stamp is None:
        return None
    return stamp.astimezone(UTC).isoformat()


def _money(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None
    if not parsed.is_finite():
        return None
    return parsed
