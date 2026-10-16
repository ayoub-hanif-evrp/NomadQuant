"""One execution-price convention for research and shadow.

Convention ``half_spread_plus_full_slippage_v1``:

- half-spread = mid × spread_bps / 10000 / 2
- slippage = mid × slippage_bps / 10000 (one full adverse basis point per side)
- buy = mid + half-spread + slippage
- sell = mid − half-spread − slippage
- commission is a separate cash item and is not inside the price

Spread and slippage are attributed for reporting. Cash moves by
quantity × execution price, plus commission on a buy and minus commission
on a sell. Attribution is not deducted again.

``combined_half_spread_and_half_slippage_v0`` is the old shadow formula,
(spread_bps + slippage_bps) / 20000. It is retained only so a verifier can
recognize historical rows. New fills must not use it.

Regulatory fees are not modeled. The extension point is ``regulatory_fee_usd``,
which stays zero until a verified schedule is supplied.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from nomadquant.research.models import CostModel

CONVENTION_ID = "half_spread_plus_full_slippage_v1"
LEGACY_SHADOW_CONVENTION_ID = "combined_half_spread_and_half_slippage_v0"

_BPS = Decimal("10000")
_TWO = Decimal("2")


def execution_price(mid: Decimal, costs: CostModel, *, side: str) -> Decimal:
    if side not in {"buy", "sell"}:
        raise ValueError(f"side must be buy or sell, got {side}")
    if mid <= 0:
        raise ValueError("execution price requires a positive mid")
    half_spread, slippage = adverse_components(mid, costs)
    if side == "buy":
        return mid + half_spread + slippage
    return mid - half_spread - slippage


def adverse_components(mid: Decimal, costs: CostModel) -> tuple[Decimal, Decimal]:
    half_spread = (mid * costs.spread_bps / _BPS) / _TWO
    slippage = mid * costs.slippage_bps / _BPS
    return half_spread, slippage


def attribute_costs(mid: Decimal, quantity: Decimal, costs: CostModel) -> dict[str, Decimal]:
    half_spread, slippage = adverse_components(mid, costs)
    return {
        "commission": costs.commission_usd,
        "spread": quantity * half_spread,
        "slippage": quantity * slippage,
        "regulatory_fee": Decimal("0"),
    }


def round_quantity(raw: Decimal, precision: int) -> Decimal:
    return raw.quantize(Decimal(10) ** -precision, rounding=ROUND_DOWN)


def legacy_shadow_execution_price(mid: Decimal, costs: CostModel, *, side: str) -> Decimal:
    """Old shadow price. Do not use for new fills."""
    half = mid * (costs.spread_bps + costs.slippage_bps) / Decimal(20000)
    if side == "buy":
        return mid + half
    if side == "sell":
        return mid - half
    raise ValueError(f"side must be buy or sell, got {side}")
