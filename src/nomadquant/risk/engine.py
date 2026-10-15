"""Deterministic, broker-independent risk engine.

``RiskEngine.evaluate`` is a pure function of its inputs: the same proposal,
ledger snapshot, prices, and policy always produce the same verdict. It never
imports a broker client, never submits an order, and never mutates the
``InternalLedger`` instance it is given (it reads a ``snapshot()`` copy
instead). A verdict here is advice for a future order gateway; this module
contains no gateway and cannot execute anything.

Rule evaluation is sequential and fails closed: the first rule that does not
PASS stops the pipeline and becomes the final verdict. REJECT and
INSUFFICIENT_DATA both block a hypothetical trade; the distinction is only
about *why* (a clear policy violation vs. data that cannot be trusted).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from nomadquant.risk.ledger import InternalLedger
from nomadquant.risk.policy import RiskPolicy
from nomadquant.risk.schemas import EvaluationResult, Proposal, RuleStatus, RuleVerdict

# Centralized to avoid magic-string drift between the two "store" call sites.
_RuleOutcome = tuple[str, RuleStatus, str]  # (rule, status, reason)


class _SeenStore(Protocol):
    """Structural type for the optional idempotency store (e.g. ``RiskStore``)."""

    def seen(self, proposal_id: str) -> bool: ...


class RiskEngine:
    """Evaluates one hypothetical proposal against a policy and a ledger snapshot."""

    def __init__(self, policy: RiskPolicy | None = None) -> None:
        self.policy = policy or RiskPolicy()

    def evaluate(
        self,
        proposal: Proposal,
        ledger: InternalLedger,
        prices: dict[str, Any],
        *,
        store: _SeenStore | None = None,
    ) -> EvaluationResult:
        """Return a verdict. Never mutates ``ledger``, never calls a broker."""
        policy = self.policy
        working_ledger = ledger.snapshot()  # engine only ever reads this copy
        rule_verdicts: list[RuleVerdict] = []

        def run(outcome: _RuleOutcome) -> bool:
            """Record one rule's outcome. Returns True if evaluation must stop."""
            rule, status, reason = outcome
            rule_verdicts.append(RuleVerdict(rule=rule, verdict=status, reason=reason))
            return status != "PASS"

        def finalize(verdict: str, **extra: Decimal | None) -> EvaluationResult:
            reasons = [rv.reason for rv in rule_verdicts if rv.verdict != "PASS"]
            return EvaluationResult(
                proposal_id=proposal.id,
                verdict=verdict,  # type: ignore[arg-type]
                reasons=reasons,
                rule_verdicts=rule_verdicts,
                policy_version=policy.version,
                policy_hash=policy.policy_hash(),
                evaluated_at=datetime.now(UTC),
                notional_usd=extra.get("notional_usd"),
                projected_cash_usd=extra.get("projected_cash_usd"),
            )

        # 1. Emergency halt is a manual kill switch and is checked first.
        if run(_emergency_halt(policy)):
            return finalize("REJECT")

        # 2. Idempotency: a proposal id already recorded is never re-approved.
        if run(_duplicate_proposal(proposal, store)):
            return finalize("REJECT")

        # 3. Domain check: only the allowed ETFs are in scope.
        if run(_unsupported_symbol(proposal, policy)):
            return finalize("REJECT")

        # 4. Quantity sanity: must be strictly positive.
        if run(_invalid_quantity(proposal)):
            return finalize("REJECT")

        # 5. Precision: fractional shares beyond the policy limit are rejected.
        if run(_quantity_precision(proposal, policy)):
            return finalize("REJECT")

        # 6. Price/as_of validity: no price, an unparsable price, or a price
        #    stamped after the proposal's as_of (look-ahead) is not usable.
        price_outcome, price, price_as_of = _extract_price(proposal, prices)
        if run(price_outcome):
            return finalize("INSUFFICIENT_DATA")

        # 7. Staleness: a technically valid price can still be too old to trust.
        if run(_stale_price(proposal, price_as_of, policy)):
            return finalize("INSUFFICIENT_DATA")

        if proposal.side == "sell":
            # 8. A hypothetical sell can only be as large as modeled holdings.
            if run(_sell_insufficient_holdings(proposal, working_ledger)):
                return finalize("REJECT")
            return finalize("APPROVE")

        # --- buy-only economic checks -------------------------------------
        notional_usd = proposal.quantity * price
        spread_cost = notional_usd * policy.spread_bps / Decimal(10000)
        total_cost = notional_usd + spread_cost + policy.commission_usd

        # 9. A proposal sized far beyond the internal $100 base is rejected
        #    outright with a message that cannot be confused with Alpaca
        #    paper buying power.
        if run(_capital_scale_sanity(notional_usd, policy)):
            return finalize("REJECT", notional_usd=notional_usd)

        # 10. The hypothetical buy must be affordable out of internal cash.
        if run(_available_cash(total_cost, working_ledger)):
            return finalize("REJECT", notional_usd=notional_usd)

        # 11. Per-transaction notional cap.
        if run(_max_single_transaction(notional_usd, policy)):
            return finalize("REJECT", notional_usd=notional_usd)

        # 12. Per-symbol concentration cap.
        if run(_max_symbol_exposure(proposal.symbol, notional_usd, price, working_ledger, policy)):
            return finalize("REJECT", notional_usd=notional_usd)

        # 13. Portfolio-wide concentration cap.
        if run(_max_total_exposure(notional_usd, prices, working_ledger, policy)):
            return finalize("REJECT", notional_usd=notional_usd)

        # 14. Minimum cash reserve after the hypothetical buy.
        cash_after = working_ledger.cash_usd - total_cost
        if run(_min_cash_reserve(cash_after, policy)):
            return finalize("REJECT", notional_usd=notional_usd, projected_cash_usd=cash_after)

        # 15. Modeled same-day loss: the transaction's own cost, as a
        #     fraction of capital. A simple cost-based proxy, not a VaR model.
        if run(_max_daily_modeled_loss(spread_cost, policy.commission_usd, policy)):
            return finalize("REJECT", notional_usd=notional_usd, projected_cash_usd=cash_after)

        return finalize("APPROVE", notional_usd=notional_usd, projected_cash_usd=cash_after)


def evaluate_proposal(
    proposal: Proposal,
    ledger: InternalLedger,
    prices: dict[str, Any],
    policy: RiskPolicy | None = None,
    *,
    store: _SeenStore | None = None,
) -> EvaluationResult:
    """Convenience wrapper around ``RiskEngine(policy).evaluate(...)``."""
    return RiskEngine(policy).evaluate(proposal, ledger, prices, store=store)


# -- individual rules ---------------------------------------------------


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
            f"Proposal id {proposal.id!r} was already evaluated (idempotency).",
        )
    return ("duplicate_proposal_id", "PASS", "Proposal id has not been evaluated before.")


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
    if proposal.quantity <= 0:
        return (
            "invalid_quantity",
            "REJECT",
            f"Quantity {proposal.quantity} must be strictly positive.",
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


def _extract_price(
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
        else:
            raw_price = quote.price
            raw_as_of = quote.as_of
        price = raw_price if isinstance(raw_price, Decimal) else Decimal(str(raw_price))
        if isinstance(raw_as_of, datetime):
            as_of = raw_as_of
        else:
            as_of = datetime.fromisoformat(str(raw_as_of))
    except (KeyError, InvalidOperation, ValueError, TypeError) as exc:
        return (
            ("missing_or_invalid_price", "INSUFFICIENT_DATA", f"Price quote is malformed: {exc}."),
            Decimal("0"),
            datetime.now(UTC),
        )
    if price <= 0:
        return (
            ("missing_or_invalid_price", "INSUFFICIENT_DATA", f"Price {price} must be positive."),
            Decimal("0"),
            datetime.now(UTC),
        )
    as_of = _as_utc(as_of)
    proposal_as_of = _as_utc(proposal.as_of)
    if as_of > proposal_as_of:
        return (
            (
                "missing_or_invalid_price",
                "INSUFFICIENT_DATA",
                "Price as_of is after the proposal's as_of (look-ahead data is not usable).",
            ),
            Decimal("0"),
            datetime.now(UTC),
        )
    outcome: _RuleOutcome = (
        "missing_or_invalid_price",
        "PASS",
        "Price data is present and well-formed.",
    )
    return (outcome, price, as_of)


def _stale_price(proposal: Proposal, price_as_of: datetime, policy: RiskPolicy) -> _RuleOutcome:
    age = _as_utc(proposal.as_of) - price_as_of
    if age > policy.max_price_age:
        return (
            "stale_price",
            "INSUFFICIENT_DATA",
            f"Price age {age} exceeds the policy limit of {policy.max_price_age}.",
        )
    return ("stale_price", "PASS", f"Price age {age} is within the policy limit.")


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
            f"Proposal notional ${notional_usd} vastly exceeds the ${policy.capital_usd} "
            "internal capital base. This engine evaluates against the internal paper "
            "ledger only and never against Alpaca account buying power.",
        )
    return ("capital_scale_sanity", "PASS", "Notional is within the internal capital scale.")


def _available_cash(total_cost: Decimal, ledger: InternalLedger) -> _RuleOutcome:
    if total_cost > ledger.cash_usd:
        return (
            "available_cash",
            "REJECT",
            f"Total cost ${total_cost} exceeds available internal cash of ${ledger.cash_usd}.",
        )
    return ("available_cash", "PASS", f"Total cost ${total_cost} is covered by internal cash.")


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
        f"Projected {symbol} exposure fraction {fraction:.4f} is within max_symbol_exposure.",
    )


def _max_total_exposure(
    notional_usd: Decimal,
    prices: dict[str, Any],
    ledger: InternalLedger,
    policy: RiskPolicy,
) -> _RuleOutcome:
    price_map: dict[str, Decimal] = {}
    for symbol, quote in prices.items():
        try:
            raw = quote["price"] if isinstance(quote, dict) else quote.price
            price_map[symbol] = raw if isinstance(raw, Decimal) else Decimal(str(raw))
        except (KeyError, InvalidOperation, ValueError, TypeError, AttributeError):
            continue
    projected = ledger.total_exposure_usd(price_map) + notional_usd
    fraction = projected / policy.capital_usd
    if fraction > policy.max_total_exposure:
        return (
            "max_total_exposure",
            "REJECT",
            f"Projected total exposure ${projected} is {fraction:.4f}x capital, "
            f"exceeding max_total_exposure ({policy.max_total_exposure}).",
        )
    return (
        "max_total_exposure",
        "PASS",
        f"Projected total exposure fraction {fraction:.4f} is within max_total_exposure.",
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


def _max_daily_modeled_loss(
    spread_cost: Decimal, commission_usd: Decimal, policy: RiskPolicy
) -> _RuleOutcome:
    modeled_loss = spread_cost + commission_usd
    limit = policy.max_daily_modeled_loss_fraction * policy.capital_usd
    if modeled_loss > limit:
        return (
            "max_daily_modeled_loss",
            "REJECT",
            f"Modeled transaction loss ${modeled_loss} exceeds "
            f"max_daily_modeled_loss_fraction limit (${limit}).",
        )
    return (
        "max_daily_modeled_loss",
        "PASS",
        f"Modeled transaction loss ${modeled_loss} is within the daily loss limit.",
    )


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
