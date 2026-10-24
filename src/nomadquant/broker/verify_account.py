"""Compare the local paper ledger with Alpaca. This command writes nothing."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from nomadquant.broker.paper_pilot import (
    _client,
    _exposure,
    _fill_activities,
    _listed_orders,
    _lookup,
    _map_status,
    _money,
    _orders,
)
from nomadquant.config import PAPER_API_URL, Settings
from nomadquant.daily.fills import load_executions
from nomadquant.daily.portfolio import build_portfolio

_PASS = "pass"
_NOTED = "noted"


def verify_paper_account(
    settings: Settings, *, client: Any | None = None, now: datetime | None = None
) -> dict[str, Any]:
    """Read local orders, fills, cash, and positions, then read Alpaca.

    The report names each mismatch. It does not submit, cancel, authorize, or
    replace a local row.
    """
    clock = now or datetime.now(UTC)
    report: dict[str, Any] = {
        "label": "READ ONLY PAPER VERIFICATION",
        "as_of": clock.isoformat(),
        "broker_orders_submitted_by_this_request": False,
        "authorization_changed": False,
        "history_rewritten": False,
        "sleeve_is_not_broker_cash": True,
        "internal_allocation_usd": "100",
        "checks": [],
        "discrepancies": [],
    }
    if settings.alpaca_base_url != PAPER_API_URL or settings.allow_order_submission:
        return _finish(report, "blocked", "non_paper_url")
    trading = client if client is not None else _client(settings)
    if trading is None:
        return _finish(report, "blocked", "credentials_absent")
    try:
        local_orders = _orders(settings.paper_path)
        executions = load_executions(settings.paper_path)
    except Exception:  # noqa: BLE001 — sqlite text is not a broker secret, but keep the kind
        return _finish(report, "blocked", "ledger_unreadable")
    try:
        account = trading.get_account()
        positions = list(trading.get_all_positions())
        broker_orders = _listed_orders(trading)
    except Exception as exc:  # noqa: BLE001 — broker text can contain secrets
        return _finish(report, "blocked", type(exc).__name__)
    if broker_orders is None:
        return _finish(report, "blocked", "broker_orders_unreadable")
    cash = _money(getattr(account, "cash", None))
    if cash is None:
        return _finish(report, "blocked", "account_amounts_unreadable")
    book = build_portfolio(local_orders, executions=executions)
    _note(
        report,
        "cash_scope",
        _NOTED,
        "Broker cash is the whole paper account. The sleeve is the internal $100 allocation.",
        account_cash_usd=format(cash, "f"),
        allocated_cash_usd=str(book["available_cash_usd"]),
    )
    _portfolio_check(report, book)
    _position_check(report, local_orders, positions)
    known = {str(row["client_order_id"]) for row in local_orders}
    for broker in broker_orders:
        client_order_id = str(getattr(broker, "client_order_id", "") or "")
        if client_order_id not in known:
            _fail(report, "broker_order_untracked", "disputed", client_order_id or "missing_id")
    for row in local_orders:
        _order_check(report, trading, row, executions)
    return _finish(report, _rollup(report), None)


def _order_check(
    report: dict[str, Any],
    trading: Any,
    row: dict[str, Any],
    executions: list[dict[str, Any]],
) -> None:
    client_order_id = str(row["client_order_id"])
    state, found = _lookup(trading, client_order_id)
    if state == "unknown":
        _fail(report, "broker_order_unreadable", "blocked", client_order_id)
        return
    if state != "found" or found is None:
        _fail(report, "local_order_missing_at_broker", "disputed", client_order_id)
        return
    mapped = _map_status(str(getattr(found, "status", "unknown")))
    if mapped != str(row.get("broker_status") or ""):
        _fail(report, "order_status_mismatch", "disputed", f"{client_order_id}:{mapped}")
    broker_qty = _money(getattr(found, "filled_qty", None)) or Decimal("0")
    local_qty = _money(row.get("filled_qty")) or Decimal("0")
    if broker_qty != local_qty:
        _fail(report, "filled_qty_mismatch", "disputed", client_order_id)
    broker_price = _money(getattr(found, "filled_avg_price", None))
    local_price = _money(row.get("filled_avg_price"))
    if local_qty > 0 and broker_price != local_price:
        _fail(report, "filled_price_mismatch", "disputed", client_order_id)
    broker_id = str(getattr(found, "id", "") or "")
    activity_state, activities = _fill_activities(trading, broker_id)
    _activity_check(
        report,
        row,
        local_qty,
        activity_state,
        activities,
        [item for item in executions if str(item["client_order_id"]) == client_order_id],
        broker_id,
    )


def _activity_check(
    report: dict[str, Any],
    order: dict[str, Any],
    filled_qty: Decimal,
    activity_state: str,
    activities: list[Any] | None,
    rows: list[dict[str, Any]],
    broker_id: str,
) -> None:
    client_order_id = str(order["client_order_id"])
    detailed = [row for row in rows if not row.get("aggregate")]
    if filled_qty <= 0 and not detailed:
        _note(report, "fills", _PASS, client_order_id)
        return
    if activity_state != "complete" or activities is None:
        _fail(
            report, "fill_history_unverified", "unverified", f"{client_order_id}:{activity_state}"
        )
        return
    matched = [item for item in activities if str(_field(item, "order_id") or "") == broker_id]
    broker_ids = {
        str(_field(item, "id") or "") for item in matched if str(_field(item, "id") or "")
    }
    local_ids = {str(row["execution_id"]) for row in detailed}
    if not local_ids:
        _fail(report, "journal_missing", "unverified", client_order_id)
        return
    if local_ids - broker_ids:
        _fail(report, "journal_execution_not_at_broker", "disputed", client_order_id)
        return
    if broker_ids - local_ids:
        _fail(report, "journal_missing_execution", "unverified", client_order_id)
        return
    total = sum((row["qty"] for row in detailed), Decimal("0"))
    activity_qty = Decimal("0")
    expected_side = _side(str(order.get("side") or ""))
    expected_symbol = str(order.get("symbol") or "").upper()
    for item in matched:
        qty = _money(_field(item, "qty"))
        if qty is None or qty <= 0:
            _fail(report, "activity_qty_unreadable", "disputed", client_order_id)
            return
        if str(_field(item, "symbol") or "").upper() != expected_symbol:
            _fail(report, "activity_symbol_mismatch", "disputed", client_order_id)
            return
        if _side(str(_field(item, "side") or "")) != expected_side:
            _fail(report, "activity_side_mismatch", "disputed", client_order_id)
            return
        activity_qty += qty
    if total != filled_qty or activity_qty != filled_qty:
        _fail(report, "journal_qty_mismatch", "disputed", client_order_id)
        return
    if any(row.get("executed_at") in {None, ""} for row in detailed):
        _fail(report, "execution_timestamp_missing", "unverified", client_order_id)
        return
    _note(report, "fills", _PASS, client_order_id)


def _side(value: str) -> str:
    lowered = value.lower()
    if "buy" in lowered:
        return "buy"
    if "sell" in lowered:
        return "sell"
    return lowered


def _portfolio_check(report: dict[str, Any], book: dict[str, Any]) -> None:
    state = str(book["accounting_state"])
    if state == "verified":
        _note(report, "portfolio", _PASS, "verified")
        return
    kind = "disputed" if state == "disputed" else "unverified"
    _fail(report, "portfolio", kind, str(book.get("accounting_reason") or state))


def _position_check(
    report: dict[str, Any], local_orders: list[dict[str, Any]], positions: list[Any]
) -> None:
    local = _exposure(local_orders)["qty"]
    broker: dict[str, Decimal] = {}
    for item in positions:
        symbol = str(getattr(item, "symbol", "")).upper()
        side = str(getattr(item, "side", "")).lower()
        qty = _money(getattr(item, "qty", None))
        if not symbol or qty is None or "short" in side or qty < 0:
            _fail(report, "broker_position_unreadable", "disputed", symbol or "unknown")
            return
        broker[symbol] = broker.get(symbol, Decimal("0")) + qty
    symbols = set(local) | set(broker)
    for symbol in sorted(symbols):
        if local.get(symbol, Decimal("0")) != broker.get(symbol, Decimal("0")):
            _fail(report, "position_qty_mismatch", "disputed", symbol)
            return
    _note(report, "positions", _PASS, ",".join(sorted(symbols)) or "flat")


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _note(report: dict[str, Any], name: str, status: str, detail: str, **extra: str) -> None:
    report["checks"].append({"name": name, "status": status, "detail": detail, **extra})


def _fail(report: dict[str, Any], name: str, status: str, detail: str) -> None:
    report["checks"].append({"name": name, "status": status, "detail": detail})
    report["discrepancies"].append({"name": name, "status": status, "detail": detail})


def _rollup(report: dict[str, Any]) -> str:
    statuses = {str(item["status"]) for item in report["checks"]}
    if "disputed" in statuses:
        return "disputed"
    if "unverified" in statuses:
        return "unverified"
    if "blocked" in statuses:
        return "blocked"
    return "healthy"


def _finish(report: dict[str, Any], readiness: str, reason: str | None) -> dict[str, Any]:
    if reason is not None:
        _fail(report, "verification", readiness, reason)
    report["readiness"] = readiness
    report["reason"] = reason
    return report
