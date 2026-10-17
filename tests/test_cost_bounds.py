"""CostModel rejects inputs that could manufacture profit or break the $100 book."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from nomadquant.finance.accounting import Book, apply_fill
from nomadquant.finance.execution import execution_price
from nomadquant.research.models import CostModel


def test_negative_and_nonfinite_costs_are_rejected() -> None:
    for payload in (
        {"commission_usd": "-0.01"},
        {"spread_bps": "-1"},
        {"slippage_bps": "-1"},
        {"min_notional_usd": "-1"},
        {"spread_bps": "NaN"},
        {"slippage_bps": "Infinity"},
        {"commission_usd": "Infinity"},
        {"quantity_precision": -1},
        {"quantity_precision": 12},
        {"spread_bps": "20001"},
    ):
        with pytest.raises(ValidationError):
            CostModel.model_validate(
                {
                    "commission_usd": "0",
                    "spread_bps": "1",
                    "slippage_bps": "1",
                    "min_notional_usd": "1",
                    "quantity_precision": 6,
                    **payload,
                }
            )


def test_hundred_dollar_buy_cannot_spend_more_than_cash() -> None:
    costs = CostModel(
        commission_usd=Decimal("0"),
        spread_bps=Decimal("1"),
        slippage_bps=Decimal("1"),
        min_notional_usd=Decimal("1"),
        quantity_precision=6,
    )
    price = execution_price(Decimal("100"), costs, side="buy")
    assert price == Decimal("100.015")
    with pytest.raises(ValueError, match="cash negative"):
        apply_fill(
            Book(cash=Decimal("100")),
            symbol="SPY",
            side="buy",
            quantity=Decimal("1"),
            mid=Decimal("100"),
            costs=costs,
        )
    book, fill = apply_fill(
        Book(cash=Decimal("100")),
        symbol="SPY",
        side="buy",
        quantity=Decimal("0.5"),
        mid=Decimal("100"),
        costs=costs,
    )
    assert book.cash > Decimal("5")
    assert book.cash + fill.notional == Decimal("100")
    assert book.holdings["SPY"] == Decimal("0.5")
    assert book.cash >= 0


def test_nonfinite_price_and_quantity_are_rejected() -> None:
    costs = CostModel()
    with pytest.raises(ValueError):
        execution_price(Decimal("NaN"), costs, side="buy")
    with pytest.raises(ValueError):
        apply_fill(
            Book(cash=Decimal("100")),
            symbol="SPY",
            side="buy",
            quantity=Decimal("0"),
            mid=Decimal("100"),
            costs=costs,
        )
