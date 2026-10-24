"""Deterministic, broker-independent risk engine.

``RiskEngine.evaluate`` never mutates the ledger, never calls a broker, and
never treats APPROVE as an executed order. Fail closed on missing valuation
or missing P&L inputs required by loss-limit rules.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

from nomadquant.finance.accounting import Book, FillResult, apply_fill
from nomadquant.finance.execution import attribute_costs, execution_price
from nomadquant.marketdata.calendar import is_session
from nomadquant.research.models import CostModel
from nomadquant.risk.ledger import InternalLedger, LedgerInvalid
from nomadquant.risk.policy import RiskPolicy
from nomadquant.risk.schemas import (
    AccountMetrics,
    EvaluationResult,
    Proposal,
    RuleStatus,
    RuleVerdict,
)

_RuleOutcome = tuple[str, RuleStatus, str]


class _SeenStore(Protocol):
    def seen(self, proposal_id: str) -> bool: ...


class RiskEngine:
    def __init__(self, policy: RiskPolicy | None = None) -> None:
        self.policy = policy or RiskPolicy()
        self.policy.validate()

    def evaluate(
        self,
        proposal: Proposal,
        ledger: InternalLedger,
        prices: dict[str, Any],
        *,
        store: _SeenStore | None = None,
        account: AccountMetrics | None = None,
        now: datetime | None = None,
        cost_basis: dict[str, Decimal] | None = None,
        clock: Literal["prospective", "historical"] = "prospective",
    ) -> EvaluationResult:
        """Return a verdict. Never mutates ``ledger``, never calls a broker."""
        policy = self.policy
        working = ledger.snapshot()
        rule_verdicts: list[RuleVerdict] = []
        if clock == "historical" and now is None:
            rule_verdicts.append(
                RuleVerdict(
                    rule="evaluation_clock",
                    verdict="INSUFFICIENT_DATA",
                    reason="Historical replay requires an explicit recorded evaluation clock.",
                )
            )
            return EvaluationResult(
                proposal_id=proposal.id,
                verdict="INSUFFICIENT_DATA",
                reasons=["Historical replay requires an explicit recorded evaluation clock."],
                rule_verdicts=rule_verdicts,
                policy_version=policy.version,
                policy_hash=policy.policy_hash(),
                evaluated_at=datetime.now(UTC),
                evaluation_clock=clock,
            )
        evaluated_at = now or datetime.now(UTC)

        def run(outcome: _RuleOutcome) -> bool:
            rule, status, reason = outcome
            rule_verdicts.append(RuleVerdict(rule=rule, verdict=status, reason=reason))
            return status != "PASS"

        def finalize(
            verdict: str,
            *,
            notional_usd: Decimal | None = None,
            projected_cash_usd: Decimal | None = None,
            projected_holdings: dict[str, Decimal] | None = None,
            projected_exposure_usd: Decimal | None = None,
            estimated_costs_usd: Decimal | None = None,
        ) -> EvaluationResult:
            reasons = [rv.reason for rv in rule_verdicts if rv.verdict != "PASS"]
            holdings_out = (
                None
                if projected_holdings is None
                else {k: str(v) for k, v in projected_holdings.items() if v != 0}
            )
            return EvaluationResult(
                proposal_id=proposal.id,
                verdict=verdict,  # type: ignore[arg-type]
                reasons=reasons,
                rule_verdicts=rule_verdicts,
                policy_version=policy.version,
                policy_hash=policy.policy_hash(),
                evaluated_at=evaluated_at,
                evaluation_clock=clock,
                notional_usd=notional_usd,
                projected_cash_usd=projected_cash_usd,
                projected_holdings=holdings_out,
                projected_exposure_usd=projected_exposure_usd,
                estimated_costs_usd=estimated_costs_usd,
            )

        if run(_emergency_halt(policy)):
            return finalize("REJECT")

        if run(_duplicate_proposal(proposal, store)):
            return finalize("REJECT")

        if run(_ledger_validity(working, policy)):
            return finalize("REJECT")

        if run(_unsupported_symbol(proposal, policy)):
            return finalize("REJECT")

        if run(_invalid_quantity(proposal)):
            return finalize("REJECT")

        if run(_quantity_precision(proposal, policy)):
            return finalize("REJECT")

        if run(_proposal_timestamp(proposal, evaluated_at)):
            return finalize("INSUFFICIENT_DATA")

        price_map, valuation = _price_map(prices)
        if run(valuation):
            return finalize("INSUFFICIENT_DATA")

        holdings_outcome = _holdings_priced(working, price_map)
        if run(holdings_outcome):
            return finalize("INSUFFICIENT_DATA")

        trade_price_outcome, trade_price, trade_as_of = _trade_price(proposal, prices)
        if run(trade_price_outcome):
            return finalize("INSUFFICIENT_DATA")

        quote = prices.get(proposal.symbol)
        if run(_session_clock(quote, trade_as_of)):
            return finalize("INSUFFICIENT_DATA")
        if run(_session_matches_market(quote, trade_as_of)):
            return finalize("INSUFFICIENT_DATA")
        if run(_feed_consistent(quote)):
            return finalize("INSUFFICIENT_DATA")
        retrieval = _retrieval_clock(quote, evaluated_at)
        if retrieval is not None and run(retrieval):
            return finalize("INSUFFICIENT_DATA")
        if run(_availability_clock(quote, evaluated_at)):
            return finalize("INSUFFICIENT_DATA")
        if run(_future_quote(trade_as_of, evaluated_at)):
            return finalize("INSUFFICIENT_DATA")
        anchor = _freshness_anchor(quote, trade_as_of)
        if anchor is None:
            rule_verdicts.append(
                RuleVerdict(
                    rule="retrieval_timestamp",
                    verdict="INSUFFICIENT_DATA",
                    reason="Price retrieval timestamp is naive.",
                )
            )
            return finalize("INSUFFICIENT_DATA")
        if run(_stale_price(anchor, evaluated_at, policy)):
            return finalize("INSUFFICIENT_DATA")
        if run(_delayed_daily(prices.get(proposal.symbol))):
            return finalize("INSUFFICIENT_DATA")

        if run(_invalid_trade_price(trade_price)):
            return finalize("INSUFFICIENT_DATA")

        # Account / drawdown checks. Cash-only empty ledgers may omit account
        # metrics; any nonzero holding without equity inputs is insufficient.
        resolved_account = _resolve_account(account, working, price_map)
        if _blocks_new_exposure(run, proposal.side, _realized_daily_loss(resolved_account, policy)):
            status = rule_verdicts[-1].verdict
            return finalize("INSUFFICIENT_DATA" if status == "INSUFFICIENT_DATA" else "REJECT")

        if _blocks_new_exposure(run, proposal.side, _unrealized_drawdown(resolved_account, policy)):
            status = rule_verdicts[-1].verdict
            return finalize("INSUFFICIENT_DATA" if status == "INSUFFICIENT_DATA" else "REJECT")

        fill, attributed = _fill_economics(proposal, trade_price, policy)
        notional = fill.notional
        costs = attributed
        mark_notional = proposal.quantity * trade_price
        if proposal.side == "buy" and run(_capital_scale_sanity(notional, policy)):
            return finalize("REJECT", notional_usd=notional, estimated_costs_usd=costs)
        if proposal.side == "sell" and proposal.quantity > working.holding(proposal.symbol):
            run(_sell_insufficient_holdings(proposal, working))
            return finalize("REJECT", notional_usd=notional, estimated_costs_usd=costs)
        debit = -fill.cash_delta if proposal.side == "buy" else Decimal("0")
        if proposal.side == "buy" and debit > working.available_cash_usd():
            run(_available_cash(debit, working))
            return finalize("REJECT", notional_usd=notional, estimated_costs_usd=costs)
        projected = _project_fill(working, proposal, trade_price, policy, cost_basis)
        if projected is None:
            rule_verdicts.append(
                RuleVerdict(
                    rule="fill_projection",
                    verdict="REJECT",
                    reason="The shared fill kernel cannot fund this quantity.",
                )
            )
            return finalize("REJECT", notional_usd=notional, estimated_costs_usd=costs)
        updated, kernel_fill, kernel_cost = projected
        if kernel_fill.notional != notional or kernel_cost != costs:
            rule_verdicts.append(
                RuleVerdict(
                    rule="fill_projection",
                    verdict="INSUFFICIENT_DATA",
                    reason="Risk economics diverged from the shared fill kernel.",
                )
            )
            return finalize("INSUFFICIENT_DATA", notional_usd=notional, estimated_costs_usd=costs)
        cash_after = updated.cash
        holdings_after = dict(updated.holdings)

        if proposal.side == "sell":
            if run(_sell_insufficient_holdings(proposal, working)):
                return finalize("REJECT", notional_usd=notional, estimated_costs_usd=costs)
            key = proposal.symbol.upper()
            try:
                exposure_after = InternalLedger(
                    cash_usd=cash_after,
                    holdings=holdings_after,
                    capital_usd=working.capital_usd,
                    reserved_cash_usd=working.reserved_cash_usd,
                ).total_exposure_usd(price_map | {key: trade_price})
            except LedgerInvalid as exc:
                run(("projected_exposure", "INSUFFICIENT_DATA", str(exc)))
                return finalize(
                    "INSUFFICIENT_DATA", notional_usd=notional, estimated_costs_usd=costs
                )
            if run(_min_cash_reserve(cash_after, policy)):
                return finalize(
                    "REJECT",
                    notional_usd=notional,
                    projected_cash_usd=cash_after,
                    projected_holdings=holdings_after,
                    projected_exposure_usd=exposure_after,
                    estimated_costs_usd=costs,
                )
            if run(_transaction_cost_budget(costs, policy)):
                return finalize(
                    "REJECT",
                    notional_usd=notional,
                    projected_cash_usd=cash_after,
                    projected_holdings=holdings_after,
                    projected_exposure_usd=exposure_after,
                    estimated_costs_usd=costs,
                )
            return finalize(
                "APPROVE",
                notional_usd=notional,
                projected_cash_usd=cash_after,
                projected_holdings=holdings_after,
                projected_exposure_usd=exposure_after,
                estimated_costs_usd=costs,
            )

        # --- buy path ------------------------------------------------------
        if run(_max_single_transaction(notional, policy)):
            return finalize("REJECT", notional_usd=notional, estimated_costs_usd=costs)

        key = proposal.symbol.upper()
        price_for_exposure = price_map | {key: trade_price}
        if run(_max_symbol_exposure(key, mark_notional, trade_price, working, policy)):
            return finalize("REJECT", notional_usd=notional, estimated_costs_usd=costs)
        try:
            exposure_after = InternalLedger(
                cash_usd=cash_after,
                holdings=holdings_after,
                capital_usd=working.capital_usd,
                reserved_cash_usd=working.reserved_cash_usd,
            ).total_exposure_usd(price_for_exposure)
        except LedgerInvalid as exc:
            run(("projected_exposure", "INSUFFICIENT_DATA", str(exc)))
            return finalize("INSUFFICIENT_DATA", notional_usd=notional, estimated_costs_usd=costs)
        if run(_max_total_exposure_value(exposure_after, policy)):
            return finalize(
                "REJECT",
                notional_usd=notional,
                projected_cash_usd=cash_after,
                projected_holdings=holdings_after,
                projected_exposure_usd=exposure_after,
                estimated_costs_usd=costs,
            )
        if run(_min_cash_reserve(cash_after, policy)):
            return finalize(
                "REJECT",
                notional_usd=notional,
                projected_cash_usd=cash_after,
                projected_holdings=holdings_after,
                projected_exposure_usd=exposure_after,
                estimated_costs_usd=costs,
            )
        if run(_transaction_cost_budget(costs, policy)):
            return finalize(
                "REJECT",
                notional_usd=notional,
                projected_cash_usd=cash_after,
                projected_holdings=holdings_after,
                projected_exposure_usd=exposure_after,
                estimated_costs_usd=costs,
            )
        return finalize(
            "APPROVE",
            notional_usd=notional,
            projected_cash_usd=cash_after,
            projected_holdings=holdings_after,
            projected_exposure_usd=exposure_after,
            estimated_costs_usd=costs,
        )


def evaluate_proposal(
    proposal: Proposal,
    ledger: InternalLedger,
    prices: dict[str, Any],
    policy: RiskPolicy | None = None,
    *,
    store: _SeenStore | None = None,
    account: AccountMetrics | None = None,
    now: datetime | None = None,
    cost_basis: dict[str, Decimal] | None = None,
    clock: Literal["prospective", "historical"] = "prospective",
) -> EvaluationResult:
    return RiskEngine(policy).evaluate(
        proposal,
        ledger,
        prices,
        store=store,
        account=account,
        now=now,
        cost_basis=cost_basis,
        clock=clock,
    )


# -- rules ------------------------------------------------------------------


def _resolve_account(
    account: AccountMetrics | None,
    ledger: InternalLedger,
    price_map: dict[str, Decimal],
) -> AccountMetrics | None:
    """Build default day metrics from cash+mark when the caller omits them.

    Realized P&L defaults to 0 for a pure mark-to-market snapshot. Callers that
    track true realized day P&L should pass ``AccountMetrics`` explicitly.
    """
    if account is not None:
        return account
    # An untouched cash book has no journal to disagree with. Any holding,
    # reservation, or cash change requires an explicit day-P&L input.
    untouched = (
        ledger.cash_usd == ledger.capital_usd
        and ledger.reserved_cash_usd == 0
        and not any(qty != 0 for qty in ledger.holdings.values())
    )
    if not untouched:
        return None
    return AccountMetrics(
        realized_pnl_today_usd=Decimal("0"),
        equity_usd=ledger.cash_usd,
        peak_equity_usd=ledger.cash_usd,
    )


def _emergency_halt(policy: RiskPolicy) -> _RuleOutcome:
    if policy.emergency_halt:
        return (
            "emergency_halt",
            "REJECT",
            "Policy emergency_halt is active; all proposals are rejected.",
        )
    return ("emergency_halt", "PASS", "Emergency halt is not active.")


def _duplicate_proposal(proposal: Proposal, store: _SeenStore | None) -> _RuleOutcome:
    if store is not None and store.seen(proposal.id):
        return (
            "duplicate_proposal_id",
            "REJECT",
            f"Proposal id {proposal.id!r} was already evaluated or reserved.",
        )
    return ("duplicate_proposal_id", "PASS", "Proposal id has not been seen.")


def _ledger_validity(ledger: InternalLedger, policy: RiskPolicy) -> _RuleOutcome:
    try:
        ledger.validate(allowed_symbols=policy.allowed_symbols)
    except LedgerInvalid as exc:
        return ("ledger_validity", "REJECT", str(exc))
    return ("ledger_validity", "PASS", "Ledger snapshot is valid.")


def _unsupported_symbol(proposal: Proposal, policy: RiskPolicy) -> _RuleOutcome:
    if proposal.symbol not in policy.allowed_symbols:
        allowed = ", ".join(sorted(policy.allowed_symbols))
        return (
            "unsupported_symbol",
            "REJECT",
            f"Symbol {proposal.symbol!r} is outside the allowed domain ({allowed}).",
        )
    return ("unsupported_symbol", "PASS", f"Symbol {proposal.symbol} is allowed.")


def _invalid_quantity(proposal: Proposal) -> _RuleOutcome:
    if proposal.quantity <= 0 or not proposal.quantity.is_finite():
        return (
            "invalid_quantity",
            "REJECT",
            f"Quantity {proposal.quantity} must be finite and strictly positive.",
        )
    return ("invalid_quantity", "PASS", "Quantity is positive.")


def _quantity_precision(proposal: Proposal, policy: RiskPolicy) -> _RuleOutcome:
    exponent = proposal.quantity.normalize().as_tuple().exponent
    decimals = -int(exponent) if isinstance(exponent, int) and exponent < 0 else 0
    if decimals > policy.max_qty_decimals:
        return (
            "quantity_precision",
            "REJECT",
            f"Quantity has {decimals} decimal places; "
            f"the policy allows at most {policy.max_qty_decimals}.",
        )
    return ("quantity_precision", "PASS", "Quantity precision is within policy.")


def _proposal_timestamp(proposal: Proposal, now: datetime) -> _RuleOutcome:
    as_of = proposal.as_of
    if as_of.tzinfo is None:
        return ("proposal_timestamp", "INSUFFICIENT_DATA", "Proposal as_of is naive.")
    if as_of > now.astimezone(UTC) + timedelta(minutes=1):
        return (
            "proposal_timestamp",
            "INSUFFICIENT_DATA",
            "Proposal as_of is in the future relative to evaluation time.",
        )
    return ("proposal_timestamp", "PASS", "Proposal as_of is usable.")


def _price_map(prices: dict[str, Any]) -> tuple[dict[str, Decimal], _RuleOutcome]:
    out: dict[str, Decimal] = {}
    for symbol, quote in prices.items():
        try:
            raw = quote["price"] if isinstance(quote, dict) else quote.price
            price = raw if isinstance(raw, Decimal) else Decimal(str(raw))
        except (KeyError, InvalidOperation, ValueError, TypeError, AttributeError) as exc:
            return (
                {},
                (
                    "price_map",
                    "INSUFFICIENT_DATA",
                    f"Malformed price for {symbol}: {exc}.",
                ),
            )
        if price <= 0 or not price.is_finite():
            return (
                {},
                (
                    "price_map",
                    "INSUFFICIENT_DATA",
                    f"Non-finite or non-positive price for {symbol}: {price}.",
                ),
            )
        out[str(symbol).upper()] = price
    return (out, ("price_map", "PASS", "Price map is well-formed."))


def _holdings_priced(ledger: InternalLedger, price_map: dict[str, Decimal]) -> _RuleOutcome:
    ok, reason = ledger.require_prices_for_holdings(price_map)
    if not ok:
        return ("holdings_valuation", "INSUFFICIENT_DATA", reason)
    return ("holdings_valuation", "PASS", reason)


def _trade_price(
    proposal: Proposal, prices: dict[str, Any]
) -> tuple[_RuleOutcome, Decimal, datetime]:
    quote = prices.get(proposal.symbol)
    if quote is None:
        return (
            ("missing_or_invalid_price", "INSUFFICIENT_DATA", "No price quote was supplied."),
            Decimal("0"),
            datetime.now(UTC),
        )
    try:
        if isinstance(quote, dict):
            raw_price = quote["price"]
            raw_as_of = quote["as_of"]
            feed = str(quote.get("feed") or "")
        else:
            raw_price = quote.price
            raw_as_of = quote.as_of
            feed = str(getattr(quote, "feed", "") or "")
        price = raw_price if isinstance(raw_price, Decimal) else Decimal(str(raw_price))
        as_of = (
            raw_as_of if isinstance(raw_as_of, datetime) else datetime.fromisoformat(str(raw_as_of))
        )
    except (KeyError, InvalidOperation, ValueError, TypeError) as exc:
        return (
            ("missing_or_invalid_price", "INSUFFICIENT_DATA", f"Price quote is malformed: {exc}."),
            Decimal("0"),
            datetime.now(UTC),
        )
    if as_of.tzinfo is None:
        return (
            (
                "missing_or_invalid_price",
                "INSUFFICIENT_DATA",
                "Price as_of must be timezone-aware.",
            ),
            Decimal("0"),
            datetime.now(UTC),
        )
    as_of = as_of.astimezone(UTC)
    proposal_as_of = proposal.as_of.astimezone(UTC)
    if as_of > proposal_as_of:
        return (
            (
                "missing_or_invalid_price",
                "INSUFFICIENT_DATA",
                "Price as_of is after the proposal's as_of (look-ahead).",
            ),
            Decimal("0"),
            datetime.now(UTC),
        )
    if not feed:
        return (
            (
                "missing_or_invalid_price",
                "INSUFFICIENT_DATA",
                "Price quote must include feed/source provenance.",
            ),
            Decimal("0"),
            datetime.now(UTC),
        )
    return (
        ("missing_or_invalid_price", "PASS", f"Trade price present ({feed})."),
        price,
        as_of,
    )


def _freshness_anchor(quote: Any, price_as_of: datetime) -> datetime | None:
    """Older of the market stamp and the retrieval stamp. Naive retrieval fails closed."""
    raw = (
        quote.get("first_retrieved_at")
        if isinstance(quote, dict)
        else getattr(quote, "first_retrieved_at", None)
    )
    if raw is None:
        return price_as_of
    retrieved = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw))
    if retrieved.tzinfo is None:
        return None
    return min(price_as_of, retrieved.astimezone(UTC))


def _session_clock(quote: Any, price_as_of: datetime) -> _RuleOutcome:
    raw = None
    if isinstance(quote, dict):
        raw = quote.get("session_date")
    else:
        raw = getattr(quote, "session_date", None)
    session_day: date
    if isinstance(raw, str):
        session_day = date.fromisoformat(raw[:10])
    elif isinstance(raw, date) and not isinstance(raw, datetime):
        session_day = raw
    else:
        session_day = price_as_of.astimezone(ZoneInfo("America/New_York")).date()
    if not is_session(session_day):
        return (
            "exchange_session",
            "INSUFFICIENT_DATA",
            f"{session_day.isoformat()} is not an NYSE session.",
        )
    return ("exchange_session", "PASS", f"{session_day.isoformat()} is an NYSE session.")


def _quote_raw(quote: Any, name: str) -> Any:
    if isinstance(quote, dict):
        return quote.get(name)
    return getattr(quote, name, None)


def _session_matches_market(quote: Any, price_as_of: datetime) -> _RuleOutcome:
    raw = _quote_raw(quote, "session_date")
    if raw is None:
        return ("session_timestamp", "PASS", "No separate session date was claimed.")
    if isinstance(raw, str):
        claimed = date.fromisoformat(raw[:10])
    elif isinstance(raw, date) and not isinstance(raw, datetime):
        claimed = raw
    else:
        return ("session_timestamp", "INSUFFICIENT_DATA", "Claimed session date is malformed.")
    observed = price_as_of.astimezone(ZoneInfo("America/New_York")).date()
    if claimed != observed:
        return (
            "session_timestamp",
            "INSUFFICIENT_DATA",
            f"Market timestamp falls on {observed.isoformat()}, "
            f"not claimed session {claimed.isoformat()}.",
        )
    return ("session_timestamp", "PASS", f"Market timestamp matches session {claimed.isoformat()}.")


def _feed_consistent(quote: Any) -> _RuleOutcome:
    feed = str(_quote_raw(quote, "feed") or "")
    source = _quote_raw(quote, "source")
    if source is not None and str(source) != feed:
        return (
            "feed_provenance",
            "INSUFFICIENT_DATA",
            f"Quote feed {feed or 'missing'} disagrees with source {source}.",
        )
    return ("feed_provenance", "PASS", f"Feed label {feed or 'missing'} is consistent.")


def _retrieval_clock(quote: Any, evaluated_at: datetime) -> _RuleOutcome | None:
    raw = _quote_raw(quote, "first_retrieved_at")
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return (
                "retrieval_timestamp",
                "INSUFFICIENT_DATA",
                "Retrieval timestamp did not parse.",
            )
    elif isinstance(raw, datetime):
        parsed = raw
    else:
        return ("retrieval_timestamp", "INSUFFICIENT_DATA", "Retrieval timestamp is malformed.")
    if parsed.tzinfo is None:
        return ("retrieval_timestamp", "INSUFFICIENT_DATA", "First retrieval timestamp is naive.")
    retrieved = parsed.astimezone(UTC)
    if retrieved > evaluated_at.astimezone(UTC) + timedelta(minutes=1):
        return (
            "future_retrieval",
            "INSUFFICIENT_DATA",
            "First retrieval is after the evaluation clock.",
        )
    return ("retrieval_timestamp", "PASS", "Retrieval timestamp is not after the evaluation clock.")


def _availability_clock(quote: Any, evaluated_at: datetime) -> _RuleOutcome:
    raw = _quote_raw(quote, "available_at")
    if raw is None:
        return (
            "observation_availability",
            "PASS",
            "No separate availability timestamp was supplied.",
        )
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return (
                "observation_availability",
                "INSUFFICIENT_DATA",
                "Availability timestamp did not parse.",
            )
    elif isinstance(raw, datetime):
        parsed = raw
    else:
        return (
            "observation_availability",
            "INSUFFICIENT_DATA",
            "Availability timestamp is malformed.",
        )
    if parsed.tzinfo is None:
        return ("observation_availability", "INSUFFICIENT_DATA", "Availability timestamp is naive.")
    available = parsed.astimezone(UTC)
    if available > evaluated_at.astimezone(UTC) + timedelta(minutes=1):
        return (
            "observation_availability",
            "INSUFFICIENT_DATA",
            "The observation was not available at the evaluation clock.",
        )
    return (
        "observation_availability",
        "PASS",
        "Observation availability is at or before evaluation.",
    )


def _future_quote(anchor: datetime, evaluated_at: datetime) -> _RuleOutcome:
    if anchor > evaluated_at.astimezone(UTC) + timedelta(minutes=1):
        return (
            "future_quote",
            "INSUFFICIENT_DATA",
            "Quote timestamp is after the evaluation clock.",
        )
    return ("future_quote", "PASS", "Quote timestamp is not after the evaluation clock.")


def _stale_price(anchor: datetime, evaluated_at: datetime, policy: RiskPolicy) -> _RuleOutcome:
    age = evaluated_at.astimezone(UTC) - anchor.astimezone(UTC)
    if age > policy.max_price_age:
        return (
            "stale_price",
            "INSUFFICIENT_DATA",
            f"Price age {age} exceeds the policy limit of {policy.max_price_age} "
            "relative to the evaluation clock.",
        )
    return ("stale_price", "PASS", f"Price age {age} is within the policy limit.")


def _delayed_daily(quote: Any) -> _RuleOutcome:
    kind = quote.get("bar_kind") if isinstance(quote, dict) else getattr(quote, "bar_kind", None)
    realtime = (
        quote.get("realtime_executable")
        if isinstance(quote, dict)
        else getattr(quote, "realtime_executable", None)
    )
    if kind == "daily" and realtime is True:
        return (
            "delayed_daily_bar",
            "INSUFFICIENT_DATA",
            "A daily bar was labeled real-time executable.",
        )
    if kind == "daily":
        return (
            "delayed_daily_bar",
            "PASS",
            "Daily bar is delayed hypothetical evidence, not a live executable price.",
        )
    return ("delayed_daily_bar", "PASS", "Quote is not labeled as a daily bar.")


def _fill_economics(
    proposal: Proposal, mid: Decimal, policy: RiskPolicy
) -> tuple[FillResult, Decimal]:
    model = _cost_model(policy)
    price = execution_price(mid, model, side=proposal.side)
    row = attribute_costs(mid, proposal.quantity, model)
    notional = proposal.quantity * price
    commission = row["commission"]
    cash_delta = -(notional + commission) if proposal.side == "buy" else notional - commission
    fill = FillResult(
        fill_price=price,
        quantity=proposal.quantity,
        side=proposal.side,
        notional=notional,
        commission=commission,
        spread_cost=row["spread"],
        slippage_cost=row["slippage"],
        regulatory_fee=row["regulatory_fee"],
        cash_delta=cash_delta,
    )
    attributed = row["spread"] + row["slippage"] + commission + row["regulatory_fee"]
    return fill, attributed


def _cost_model(policy: RiskPolicy) -> CostModel:
    return CostModel(
        commission_usd=policy.commission_usd,
        spread_bps=policy.spread_bps,
        slippage_bps=policy.slippage_bps,
        min_notional_usd=Decimal("0"),
        quantity_precision=policy.max_qty_decimals,
    )


def _project_fill(
    ledger: InternalLedger,
    proposal: Proposal,
    mid: Decimal,
    policy: RiskPolicy,
    cost_basis: dict[str, Decimal] | None,
) -> tuple[Book, FillResult, Decimal] | None:
    model = _cost_model(policy)
    book = Book(
        cash=ledger.cash_usd,
        holdings={key.upper(): value for key, value in ledger.holdings.items()},
        cost_basis={key.upper(): value for key, value in dict(cost_basis or {}).items()},
    )
    try:
        updated, fill = apply_fill(
            book,
            symbol=proposal.symbol,
            side=proposal.side,
            quantity=proposal.quantity,
            mid=mid,
            costs=model,
        )
    except ValueError:
        return None
    attributed = fill.spread_cost + fill.slippage_cost + fill.commission + fill.regulatory_fee
    return updated, fill, attributed


def _invalid_trade_price(price: Decimal) -> _RuleOutcome:
    if price <= 0 or not price.is_finite():
        return (
            "trade_price_finite",
            "INSUFFICIENT_DATA",
            f"Trade price {price} is not a finite positive number.",
        )
    return ("trade_price_finite", "PASS", "Trade price is finite and positive.")


def _sell_insufficient_holdings(proposal: Proposal, ledger: InternalLedger) -> _RuleOutcome:
    held = ledger.holding(proposal.symbol)
    if proposal.quantity > held:
        return (
            "sell_insufficient_holdings",
            "REJECT",
            f"Hypothetical sell of {proposal.quantity} {proposal.symbol} exceeds "
            f"modeled holdings of {held}.",
        )
    return ("sell_insufficient_holdings", "PASS", f"Modeled holdings of {held} cover this sell.")


def _capital_scale_sanity(notional_usd: Decimal, policy: RiskPolicy) -> _RuleOutcome:
    if notional_usd > policy.capital_usd:
        return (
            "capital_scale_sanity",
            "REJECT",
            f"Proposal notional ${notional_usd} exceeds the ${policy.capital_usd} "
            "internal capital base (never Alpaca buying power).",
        )
    return ("capital_scale_sanity", "PASS", "Notional is within the internal capital scale.")


def _available_cash(total_cost: Decimal, ledger: InternalLedger) -> _RuleOutcome:
    available = ledger.available_cash_usd()
    if total_cost > available:
        return (
            "available_cash",
            "REJECT",
            f"Total debit ${total_cost} exceeds available internal cash of ${available} "
            f"(cash ${ledger.cash_usd} minus reserved ${ledger.reserved_cash_usd}).",
        )
    return ("available_cash", "PASS", f"Total debit ${total_cost} is covered by available cash.")


def _max_single_transaction(notional_usd: Decimal, policy: RiskPolicy) -> _RuleOutcome:
    if notional_usd > policy.max_single_transaction_usd:
        return (
            "max_single_transaction_usd",
            "REJECT",
            f"Notional ${notional_usd} exceeds max_single_transaction_usd "
            f"(${policy.max_single_transaction_usd}).",
        )
    return (
        "max_single_transaction_usd",
        "PASS",
        f"Notional ${notional_usd} is within max_single_transaction_usd.",
    )


def _max_symbol_exposure(
    symbol: str,
    notional_usd: Decimal,
    price: Decimal,
    ledger: InternalLedger,
    policy: RiskPolicy,
) -> _RuleOutcome:
    projected = ledger.symbol_exposure_usd(symbol, price) + notional_usd
    fraction = projected / policy.capital_usd
    if fraction > policy.max_symbol_exposure:
        return (
            "max_symbol_exposure",
            "REJECT",
            f"Projected {symbol} exposure ${projected} is {fraction:.4f}x capital, "
            f"exceeding max_symbol_exposure ({policy.max_symbol_exposure}).",
        )
    return (
        "max_symbol_exposure",
        "PASS",
        f"Projected {symbol} exposure fraction {fraction:.4f} is within limit.",
    )


def _max_total_exposure_value(exposure_after: Decimal, policy: RiskPolicy) -> _RuleOutcome:
    fraction = exposure_after / policy.capital_usd
    if fraction > policy.max_total_exposure:
        return (
            "max_total_exposure",
            "REJECT",
            f"Projected total exposure ${exposure_after} is {fraction:.4f}x capital, "
            f"exceeding max_total_exposure ({policy.max_total_exposure}).",
        )
    return (
        "max_total_exposure",
        "PASS",
        f"Projected total exposure fraction {fraction:.4f} is within limit.",
    )


def _min_cash_reserve(cash_after: Decimal, policy: RiskPolicy) -> _RuleOutcome:
    if cash_after < policy.min_cash_reserve_usd:
        return (
            "min_cash_reserve_usd",
            "REJECT",
            f"Projected remaining cash ${cash_after} is below min_cash_reserve_usd "
            f"(${policy.min_cash_reserve_usd}).",
        )
    return (
        "min_cash_reserve_usd",
        "PASS",
        f"Projected remaining cash ${cash_after} meets min_cash_reserve_usd.",
    )


def _transaction_cost_budget(costs: Decimal, policy: RiskPolicy) -> _RuleOutcome:
    """Spread+commission budget only — not a portfolio drawdown breaker."""
    limit = policy.max_transaction_cost_fraction * policy.capital_usd
    if costs > limit:
        return (
            "transaction_cost_budget",
            "REJECT",
            f"Estimated transaction costs ${costs} exceed cost budget (${limit}).",
        )
    return (
        "transaction_cost_budget",
        "PASS",
        f"Estimated transaction costs ${costs} are within the cost budget.",
    )


def _blocks_new_exposure(
    run: Callable[[_RuleOutcome], bool], side: str, outcome: _RuleOutcome
) -> bool:
    """A loss or drawdown breaker stops new buys. A sell may still reduce risk."""
    rule, status, reason = outcome
    if side == "sell" and status == "REJECT":
        run((rule, "PASS", f"{reason} A risk-reducing sell remains allowed."))
        return False
    return run(outcome)


def _realized_daily_loss(account: AccountMetrics | None, policy: RiskPolicy) -> _RuleOutcome:
    if account is None or account.realized_pnl_today_usd is None:
        return (
            "realized_daily_loss",
            "INSUFFICIENT_DATA",
            "Realized daily P&L is required for the daily-loss circuit breaker.",
        )
    pnl = account.realized_pnl_today_usd
    if not pnl.is_finite():
        return ("realized_daily_loss", "INSUFFICIENT_DATA", "Realized daily P&L is not finite.")
    limit = -(policy.max_realized_daily_loss_fraction * policy.capital_usd)
    if pnl < limit:
        return (
            "realized_daily_loss",
            "REJECT",
            f"Realized daily P&L ${pnl} breaches loss limit (${limit}).",
        )
    return ("realized_daily_loss", "PASS", f"Realized daily P&L ${pnl} is within limit.")


def _unrealized_drawdown(account: AccountMetrics | None, policy: RiskPolicy) -> _RuleOutcome:
    if account is None or account.equity_usd is None or account.peak_equity_usd is None:
        return (
            "unrealized_drawdown",
            "INSUFFICIENT_DATA",
            "Equity and peak equity are required for the drawdown circuit breaker.",
        )
    equity = account.equity_usd
    peak = account.peak_equity_usd
    if not equity.is_finite() or not peak.is_finite() or peak <= 0:
        return (
            "unrealized_drawdown",
            "INSUFFICIENT_DATA",
            "Equity/peak equity values are not usable.",
        )
    drawdown = (peak - equity) / peak
    if drawdown > policy.max_unrealized_drawdown_fraction:
        return (
            "unrealized_drawdown",
            "REJECT",
            f"Unrealized drawdown {drawdown:.4f} exceeds "
            f"max_unrealized_drawdown_fraction ({policy.max_unrealized_drawdown_fraction}).",
        )
    return (
        "unrealized_drawdown",
        "PASS",
        f"Unrealized drawdown {drawdown:.4f} is within limit.",
    )
