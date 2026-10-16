"""Deterministic policy-aware sizing. Keeps strategy target; caps feasible qty."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from nomadquant.research.models import CostModel
from nomadquant.risk.policy import RiskPolicy

_ZERO = Decimal("0")


@dataclass(frozen=True)
class SizedOrder:
    desired_target_weight: Decimal
    feasible_weight: Decimal
    residual_target_weight: Decimal
    quantity: Decimal
    side: str | None
    limit_price: Decimal
    max_notional_usd: Decimal
    is_partial: bool
    reason: str


def size_policy_aware(
    *,
    cash: Decimal,
    reserved: Decimal,
    qty: Decimal,
    target_weight: Decimal,
    price: Decimal,
    costs: CostModel,
    policy: RiskPolicy,
) -> SizedOrder:
    """Size toward target without exceeding policy max single transaction.

    Does not split into multiple trades to bypass limits.
    """
    available = cash - reserved
    if available < 0:
        available = _ZERO
    if price <= 0:
        return SizedOrder(
            desired_target_weight=target_weight,
            feasible_weight=_ZERO,
            residual_target_weight=target_weight,
            quantity=_ZERO,
            side=None,
            limit_price=price,
            max_notional_usd=_ZERO,
            is_partial=False,
            reason="Invalid price.",
        )
    if policy.emergency_halt:
        return SizedOrder(
            desired_target_weight=target_weight,
            feasible_weight=(qty * price) / (cash + qty * price)
            if cash + qty * price > 0
            else _ZERO,
            residual_target_weight=target_weight,
            quantity=_ZERO,
            side=None,
            limit_price=price,
            max_notional_usd=_ZERO,
            is_partial=False,
            reason="Emergency halt active.",
        )

    equity = cash + qty * price
    if equity <= 0:
        return SizedOrder(
            desired_target_weight=target_weight,
            feasible_weight=_ZERO,
            residual_target_weight=target_weight,
            quantity=_ZERO,
            side=None,
            limit_price=price,
            max_notional_usd=_ZERO,
            is_partial=False,
            reason="Non-positive equity.",
        )

    desired_value = equity * target_weight
    current_value = qty * price
    delta = desired_value - current_value
    if abs(delta) < costs.min_notional_usd:
        return SizedOrder(
            desired_target_weight=target_weight,
            feasible_weight=(current_value / equity).quantize(Decimal("0.000001")),
            residual_target_weight=_ZERO,
            quantity=_ZERO,
            side=None,
            limit_price=price,
            max_notional_usd=_ZERO,
            is_partial=False,
            reason="Delta below minimum notional.",
        )

    max_tx = policy.max_single_transaction_usd
    # Exposure limit is a fraction of capital (not a free-standing USD field).
    max_exposure_usd = policy.max_total_exposure * policy.capital_usd
    headroom_exposure = max(_ZERO, max_exposure_usd - current_value)

    if delta > 0:
        fill = price * (1 + (costs.spread_bps + costs.slippage_bps) / Decimal(20000))
        budget_cash = max(_ZERO, available - costs.commission_usd - policy.min_cash_reserve_usd)
        spend_cap = min(delta, max_tx, budget_cash, headroom_exposure)
        if spend_cap < costs.min_notional_usd:
            return SizedOrder(
                desired_target_weight=target_weight,
                feasible_weight=(current_value / equity).quantize(Decimal("0.000001")),
                residual_target_weight=target_weight - (current_value / equity),
                quantity=_ZERO,
                side=None,
                limit_price=fill,
                max_notional_usd=spend_cap,
                is_partial=False,
                reason=(
                    "No valid buy quantity under cash/reserve/max_single_transaction/"
                    "max_exposure/min_notional constraints."
                ),
            )
        q = (spend_cap / fill).quantize(
            Decimal(10) ** -costs.quantity_precision, rounding=ROUND_DOWN
        )
        if q <= 0:
            return SizedOrder(
                desired_target_weight=target_weight,
                feasible_weight=(current_value / equity).quantize(Decimal("0.000001")),
                residual_target_weight=target_weight - (current_value / equity),
                quantity=_ZERO,
                side=None,
                limit_price=fill,
                max_notional_usd=spend_cap,
                is_partial=False,
                reason="Quantity rounds to zero under precision.",
            )
        filled_value = q * fill
        new_weight = (current_value + filled_value) / equity
        residual = target_weight - new_weight
        is_partial = filled_value + Decimal("0.01") < delta
        reason = (
            "Partial simulated target adjustment: capped by max_single_transaction_usd "
            f"({max_tx}) and/or cash/exposure constraints."
            if is_partial
            else "Sized to full desired delta within policy."
        )
        return SizedOrder(
            desired_target_weight=target_weight,
            feasible_weight=new_weight.quantize(Decimal("0.000001")),
            residual_target_weight=max(_ZERO, residual).quantize(Decimal("0.000001")),
            quantity=q,
            side="buy",
            limit_price=fill,
            max_notional_usd=max_tx,
            is_partial=is_partial,
            reason=reason,
        )

    # Sell
    fill = price * (1 - (costs.spread_bps + costs.slippage_bps) / Decimal(20000))
    sell_value = -delta
    sell_cap = min(sell_value, max_tx, current_value)
    if sell_cap < costs.min_notional_usd or qty <= 0:
        return SizedOrder(
            desired_target_weight=target_weight,
            feasible_weight=(current_value / equity).quantize(Decimal("0.000001")),
            residual_target_weight=abs(target_weight - current_value / equity),
            quantity=_ZERO,
            side=None,
            limit_price=fill,
            max_notional_usd=sell_cap,
            is_partial=False,
            reason="No valid sell quantity under policy/min_notional.",
        )
    q = min(
        qty,
        (sell_cap / fill).quantize(Decimal(10) ** -costs.quantity_precision, rounding=ROUND_DOWN),
    )
    if q <= 0:
        return SizedOrder(
            desired_target_weight=target_weight,
            feasible_weight=(current_value / equity).quantize(Decimal("0.000001")),
            residual_target_weight=_ZERO,
            quantity=_ZERO,
            side=None,
            limit_price=fill,
            max_notional_usd=sell_cap,
            is_partial=False,
            reason="Sell quantity rounds to zero.",
        )
    filled_value = q * fill
    new_weight = (current_value - filled_value) / equity
    residual = abs(target_weight - new_weight)
    is_partial = filled_value + Decimal("0.01") < sell_value
    reason = (
        "Partial simulated target adjustment on sell: capped by max_single_transaction_usd."
        if is_partial
        else "Sized sell to desired delta within policy."
    )
    return SizedOrder(
        desired_target_weight=target_weight,
        feasible_weight=new_weight.quantize(Decimal("0.000001")),
        residual_target_weight=residual.quantize(Decimal("0.000001")),
        quantity=q,
        side="sell",
        limit_price=fill,
        max_notional_usd=max_tx,
        is_partial=is_partial,
        reason=reason,
    )
