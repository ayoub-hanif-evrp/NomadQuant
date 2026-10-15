"""Pydantic contracts for the risk engine. Hypothetical evaluation only."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Side = Literal["buy", "sell"]
Verdict = Literal["APPROVE", "REJECT", "INSUFFICIENT_DATA"]
RuleStatus = Literal["PASS", "REJECT", "INSUFFICIENT_DATA"]


class Proposal(BaseModel):
    """A hypothetical order for the risk engine. Never executed."""

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

    @field_validator("as_of")
    @classmethod
    def _aware_as_of(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Proposal as_of must be timezone-aware.")
        return value


class PriceQuote(BaseModel):
    """Caller-supplied market observation. The engine never fetches prices."""

    model_config = ConfigDict(extra="ignore")

    price: Decimal
    as_of: datetime
    feed: str = ""

    @field_validator("as_of")
    @classmethod
    def _aware_as_of(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Price as_of must be timezone-aware.")
        return value


class AccountMetrics(BaseModel):
    """Optional day P&L / equity inputs for loss-limit rules.

    Missing fields cause INSUFFICIENT_DATA for the corresponding rule rather
    than silently treating loss as zero.
    """

    model_config = ConfigDict(extra="forbid")

    realized_pnl_today_usd: Decimal | None = None
    equity_usd: Decimal | None = None
    peak_equity_usd: Decimal | None = None


class RuleVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: str
    verdict: RuleStatus
    reason: str


class EvaluationResult(BaseModel):
    """Full result of one evaluate call. Never an executed broker order."""

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
    projected_holdings: dict[str, str] | None = None
    projected_exposure_usd: Decimal | None = None
    estimated_costs_usd: Decimal | None = None
    is_hypothetical: Literal[True] = True
    is_broker_order: Literal[False] = False
