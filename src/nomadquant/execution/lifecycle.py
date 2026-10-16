"""Deterministic fake order lifecycle. No network and no Alpaca client.

An ambiguous submission result is UNKNOWN. It is not a failure, and it is not
retried automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

_TERMINAL = {"filled", "rejected", "canceled", "reconciled"}


@dataclass
class SimOrder:
    client_order_id: str
    state: str = "intent"
    quantity: Decimal = Decimal("0")
    filled_qty: Decimal = Decimal("0")
    reserved: bool = False
    ledger_committed: bool = False
    attempts: int = 0
    warnings: list[str] = field(default_factory=list)


def apply_event(order: SimOrder, event: str, *, broker_state: str | None = None) -> SimOrder:
    """Advance one fake order. Duplicate terminal events are ignored."""
    if event == "risk_checked" and order.state == "intent":
        order.state = "risk_checked"
    elif event == "reserved" and order.state == "risk_checked":
        order.state = "reserved"
        order.reserved = True
    elif event == "submitted" and order.state == "reserved":
        order.state = "submitted"
        order.attempts += 1
    elif event == "acknowledged" and order.state == "submitted":
        order.state = "acknowledged"
    elif event == "partial_fill" and order.state in {"submitted", "acknowledged", "partial"}:
        order.state = "partial"
        order.filled_qty = min(order.quantity, order.filled_qty + (order.quantity / 2))
    elif event == "filled" and order.state in {"submitted", "acknowledged", "partial"}:
        order.state = "filled"
        order.filled_qty = order.quantity
    elif event == "rejected" and order.state in {"submitted", "acknowledged", "risk_checked"}:
        order.state = "rejected"
    elif event == "canceled" and order.state in {"submitted", "acknowledged", "partial"}:
        order.state = "canceled"
    elif event == "timeout":
        order.state = "unknown"
        order.warnings.append("Submission result is UNKNOWN. Do not retry blindly.")
    elif event == "retry":
        if order.state == "unknown":
            raise BlindRetryForbidden(order.client_order_id)
        order.warnings.append("Retry ignored because the order is not in a safe state.")
    elif event == "duplicate":
        order.warnings.append("Duplicate update ignored.")
    elif event == "out_of_order_fill" and order.state in {"intent", "risk_checked", "reserved"}:
        order.warnings.append("Fill arrived before submission and was not applied.")
    elif event == "crash_after_reservation":
        order.reserved = True
        order.ledger_committed = False
        order.warnings.append("Process stopped after reservation. Recovery is required.")
    elif event == "crash_after_commit":
        order.ledger_committed = True
        order.state = "filled" if order.filled_qty == order.quantity else order.state
        order.warnings.append("Ledger commit survived the crash. Do not apply it twice.")
    elif event == "replay_commit":
        if order.ledger_committed:
            order.warnings.append("Commit replay was idempotent.")
        else:
            order.ledger_committed = True
    elif event == "broker_lookup":
        if broker_state:
            order.state = "reconciled"
            order.warnings.append(f"Broker record found by client order id as {broker_state}.")
        else:
            order.state = "unknown"
            order.warnings.append("No broker record after a safe lookup. Result remains UNKNOWN.")
    elif event == "outbox_failure":
        order.warnings.append("Outbox delivery failed. The order state was not guessed.")
    else:
        order.warnings.append(f"Event {event} did not change state {order.state}.")
    return order


class BlindRetryForbidden(RuntimeError):
    pass


def run_script(
    client_order_id: str,
    events: list[str],
    *,
    quantity: Decimal = Decimal("1"),
    broker_state: str | None = None,
) -> SimOrder:
    order = SimOrder(client_order_id=client_order_id, quantity=quantity)
    for event in events:
        apply_event(order, event, broker_state=broker_state)
    return order
