"""Deterministic, broker-independent risk engine.

``RiskEngine.evaluate`` never mutates the ledger, never calls a broker, and
never treats APPROVE as an executed order. Fail closed on missing valuation
or missing P&L inputs required by loss-limit rules.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

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
    ) -> EvaluationResult:
        """Return a verdict. Never mutates ``ledger``, never calls a broker."""
        policy = self.policy
        working = ledger.snapshot()
        rule_verdicts: list[RuleVerdict] = []
        clock = now or datetime.now(UTC)

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
                evaluated_at=clock,
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

        if run(_proposal_timestamp(proposal, clock)):
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

        if run(_stale_price(proposal, trade_as_of, policy)):
            return finalize("INSUFFICIENT_DATA")

        if run(_invalid_trade_price(trade_price)):
            return finalize("INSUFFICIENT_DATA")

        # Account / drawdown checks. Cash-only empty ledgers may omit account
        # metrics; any nonzero holding without equity inputs is insufficient.
        resolved_account = _resolve_account(account, working, price_map)
        if run(_realized_daily_loss(resolved_account, policy)):
            status = rule_verdicts[-1].verdict
            return finalize("INSUFFICIENT_DATA" if status == "INSUFFICIENT_DATA" else "REJECT")

        if run(_unrealized_drawdown(resolved_account, policy)):
            status = rule_verdicts[-1].verdict
            return finalize("INSUFFICIENT_DATA" if status == "INSUFFICIENT_DATA" else "REJECT")

        notional = proposal.quantity * trade_price
        spread_cost = notional * policy.spread_bps / Decimal(10000)
        commission = policy.commission_usd
        costs = spread_cost + commission

        if proposal.side == "sell":
            if run(_sell_insufficient_holdings(proposal, working)):
                return finalize("REJECT", notional_usd=notional, estimated_costs_usd=costs)
            proceeds = notional - costs
            cash_after = working.cash_usd + proceeds
            holdings_after = dict(working.holdings)
            key = proposal.symbol.upper()
            holdings_after[key] = working.holding(key) - proposal.quantity
            if holdings_after[key] == 0:
                holdings_after.pop(key, None)
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
        total_debit = notional + costs
        if run(_capital_scale_sanity(notional, policy)):
            return finalize("REJECT", notional_usd=notional, estimated_costs_usd=costs)
        if run(_available_cash(total_debit, working)):
            return finalize("REJECT", notional_usd=notional, estimated_costs_usd=costs)
        if run(_max_single_transaction(notional, policy)):
            return finalize("REJECT", notional_usd=notional, estimated_costs_usd=costs)

        cash_after = working.cash_usd - total_debit
        holdings_after = dict(working.holdings)
        key = proposal.symbol.upper()
        holdings_after[key] = working.holding(key) + proposal.quantity
        price_for_exposure = price_map | {key: trade_price}
        if run(_max_symbol_exposure(key, notional, trade_price, working, policy)):
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
) -> EvaluationResult:
    return RiskEngine(policy).evaluate(
        proposal, ledger, prices, store=store, account=account, now=now
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
    try:
        exposure = (
            ledger.total_exposure_usd(price_map)
            if any(qty != 0 for qty in ledger.holdings.values())
            else Decimal("0")
        )
    except LedgerInvalid:
        return None
    equity = ledger.cash_usd + exposure
    # Do not invent a peak above current equity — that would fabricate drawdown.
    # Callers tracking true peaks must pass AccountMetrics explicitly.
    return AccountMetrics(
        realized_pnl_today_usd=Decimal("0"),
        equity_usd=equity,
        peak_equity_usd=equity,
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


def _stale_price(proposal: Proposal, price_as_of: datetime, policy: RiskPolicy) -> _RuleOutcome:
    age = proposal.as_of.astimezone(UTC) - price_as_of
    if age > policy.max_price_age:
        return (
            "stale_price",
            "INSUFFICIENT_DATA",
            f"Price age {age} exceeds the policy limit of {policy.max_price_age}.",
        )
    return ("stale_price", "PASS", f"Price age {age} is within the policy limit.")


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
