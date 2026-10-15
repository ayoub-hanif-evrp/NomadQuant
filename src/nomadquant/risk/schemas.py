"""Pydantic contracts for the risk engine.

A ``Proposal`` describes a hypothetical trade for ``RiskEngine.evaluate``. It
is never a broker order: constructing or evaluating one does nothing to
Alpaca and does nothing to the internal ledger. ``EvaluationResult`` records
every rule outcome so a human can audit why a proposal was approved or
rejected.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Side = Literal["buy", "sell"]
Verdict = Literal["APPROVE", "REJECT", "INSUFFICIENT_DATA"]
RuleStatus = Literal["PASS", "REJECT", "INSUFFICIENT_DATA"]


class Proposal(BaseModel):
    """A hypothetical order for the risk engine to evaluate. Never executed.

    ``id`` is the idempotency key used by ``RiskStore`` to refuse re-evaluating
    the same proposal twice. ``source`` identifies the caller (for example
    ``"cli"`` or ``"agent"``) for audit purposes only; it has no effect on the
    verdict.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=200)
    symbol: str = Field(min_length=1, max_length=20)
    side: Side
    quantity: Decimal
    limit_price: Decimal | None = None
    as_of: datetime
    agent_run_id: int | None = None

    @field_validator("symbol")
    @classmethod
    def _normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class PriceQuote(BaseModel):
    """A single market data point supplied by the caller.

    The risk engine never fetches prices itself; it only evaluates whatever
    snapshot the caller passes in, so there is no network or broker call
    hidden inside the engine.
    """

    model_config = ConfigDict(extra="ignore")

    price: Decimal
    as_of: datetime
    feed: str = ""


class RuleVerdict(BaseModel):
    """Outcome of one rule check within an evaluation."""

    model_config = ConfigDict(extra="forbid")

    rule: str
    verdict: RuleStatus
    reason: str


class EvaluationResult(BaseModel):
    """Full result of one ``RiskEngine.evaluate`` call. Hypothetical only.

    Evaluating a proposal never mutates the internal ledger and never calls a
    broker. ``is_hypothetical``/``is_broker_order`` are fixed literals so a
    downstream consumer cannot mistake this for an executed trade.
    """

    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    verdict: Verdict
    reasons: list[str] = Field(default_factory=list)
    rule_verdicts: list[RuleVerdict] = Field(default_factory=list)
    policy_version: str
    policy_hash: str
    evaluated_at: datetime
    notional_usd: Decimal | None = None
    projected_cash_usd: Decimal | None = None
    is_hypothetical: Literal[True] = True
    is_broker_order: Literal[False] = False
