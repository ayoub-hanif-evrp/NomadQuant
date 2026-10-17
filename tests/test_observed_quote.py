"""Observed quotes never invent a fill and never use a closed-market Friday print."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nomadquant.research.models import CostModel
from nomadquant.risk.policy import RiskPolicy
from nomadquant.shadow.observed_quote import (
    EXECUTION_OBSERVED_QUOTE,
    QuoteObservation,
    quote_from_snapshot,
    simulate_observed_fill,
)

_COSTS = CostModel(
    commission_usd=Decimal("0"),
    spread_bps=Decimal("1"),
    slippage_bps=Decimal("1"),
    min_notional_usd=Decimal("1"),
    quantity_precision=6,
)
_NOW = datetime(2026, 10, 19, 14, 0, tzinfo=UTC)


def _quote(**overrides: object) -> QuoteObservation:
    payload = {
        "symbol": "SPY",
        "feed": "iex",
        "bid": Decimal("100"),
        "ask": Decimal("100.02"),
        "market_timestamp": _NOW - timedelta(seconds=5),
        "retrieved_at": _NOW - timedelta(seconds=1),
        "source": "test",
    }
    payload.update(overrides)
    return QuoteObservation(**payload)  # type: ignore[arg-type]


def test_open_market_buy_uses_the_ask_and_respects_the_fifty_dollar_cap() -> None:
    result = simulate_observed_fill(
        _quote(),
        side="buy",
        decision_time=_NOW,
        market_open=True,
        cash=Decimal("100"),
        held_quantity=Decimal("0"),
        costs=_COSTS,
        policy=RiskPolicy(),
        estimated_mid=Decimal("100.01"),
    )
    assert result["status"] == "SIMULATED_FILL"
    assert result["execution_model"] == EXECUTION_OBSERVED_QUOTE
    assert Decimal(result["observed_price"]) > Decimal("100.02")
    assert Decimal(result["notional"]) <= Decimal("50")
    assert Decimal(result["notional"]) <= Decimal("95")
    assert result["broker_orders"] is False
    assert result["used_by_registered_strategy"] is False


def test_missing_stale_closed_and_future_quotes_do_not_fill() -> None:
    missing = simulate_observed_fill(
        None,
        side="buy",
        decision_time=_NOW,
        market_open=True,
        cash=Decimal("100"),
        held_quantity=Decimal("0"),
        costs=_COSTS,
    )
    assert missing["status"] == "WAIT"
    closed = simulate_observed_fill(
        _quote(),
        side="buy",
        decision_time=_NOW,
        market_open=False,
        cash=Decimal("100"),
        held_quantity=Decimal("0"),
        costs=_COSTS,
    )
    assert closed["status"] == "NO_FILL"
    assert closed["reason"] == "market_closed_stale_quote_refused"
    future = simulate_observed_fill(
        _quote(
            market_timestamp=_NOW + timedelta(seconds=5),
            retrieved_at=_NOW + timedelta(seconds=6),
        ),
        side="buy",
        decision_time=_NOW,
        market_open=True,
        cash=Decimal("100"),
        held_quantity=Decimal("0"),
        costs=_COSTS,
    )
    assert future["reason"] == "quote_known_only_after_decision"
    crossed = simulate_observed_fill(
        _quote(bid=Decimal("101"), ask=Decimal("100")),
        side="buy",
        decision_time=_NOW,
        market_open=True,
        cash=Decimal("100"),
        held_quantity=Decimal("0"),
        costs=_COSTS,
    )
    assert crossed["reason"] == "bid_ask_unusable"


def test_snapshot_parser_reads_bid_ask_and_ignores_a_trade_only_payload() -> None:
    retrieved = datetime(2026, 10, 19, 14, 0, tzinfo=UTC)
    parsed = quote_from_snapshot(
        "SPY",
        {"latestQuote": {"bp": "763.1", "ap": "763.2", "t": "2026-10-19T13:59:55Z"}},
        retrieved_at=retrieved,
    )
    assert parsed is not None
    assert parsed.feed == "iex"
    assert parsed.bid == Decimal("763.1")
    assert quote_from_snapshot("SPY", {"latestTrade": {"p": 1}}, retrieved_at=retrieved) is None
