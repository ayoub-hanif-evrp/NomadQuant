"""Typed execution interface for a future paper gateway.

This module MUST NOT call Alpaca TradingClient or submit_order. The only
implemented adapter is ``DryRunExecutionGateway``, which records intent and
returns a denied/simulated result without network I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

ExecutionStatus = Literal[
    "denied_default",
    "dry_run_accepted",
    "reserved",
    "rejected",
    "error",
]


@dataclass(frozen=True)
class ExecutionRequest:
    """Broker-order shaped contract. Never sent to a broker in this phase."""

    idempotency_key: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    proposal_id: str
    risk_verdict: str
    reserved_cash_usd: Decimal
    policy_hash: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class ExecutionResult:
    status: ExecutionStatus
    request: ExecutionRequest
    reason: str
    broker_order_id: str | None = None
    is_broker_order: Literal[False] = False


class DryRunExecutionGateway:
    """Default-deny / dry-run adapter. No network, no Alpaca imports."""

    def __init__(self, *, allow_order_submission: bool = False) -> None:
        if allow_order_submission:
            raise ValueError(
                "DryRunExecutionGateway refuses allow_order_submission=True. "
                "Paper order submission is not implemented in this milestone."
            )
        self.allow_order_submission = False
        self._log: list[ExecutionResult] = []

    def submit(self, request: ExecutionRequest) -> ExecutionResult:
        if request.risk_verdict != "APPROVE":
            result = ExecutionResult(
                status="rejected",
                request=request,
                reason="Risk verdict is not APPROVE; execution denied.",
            )
        else:
            result = ExecutionResult(
                status="dry_run_accepted",
                request=request,
                reason=(
                    "Dry-run only. Reserved-capital and idempotency key were noted; "
                    "no Alpaca order was submitted."
                ),
                broker_order_id=None,
            )
        self._log.append(result)
        return result

    def history(self) -> list[ExecutionResult]:
        return list(self._log)
