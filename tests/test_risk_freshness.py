"""Prospective freshness uses the evaluation clock, not the proposal's own stamp."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nomadquant.risk import InternalLedger, Proposal, RiskEngine, RiskPolicy

TODAY = datetime(2026, 10, 16, 15, 0, tzinfo=UTC)
RETRIEVED = TODAY - timedelta(days=3)


def _proposal(as_of: datetime) -> Proposal:
    return Proposal(
        id="stale-1",
        source="test",
        symbol="SPY",
        side="buy",
        quantity=Decimal("0.01"),
        as_of=as_of,
    )


def test_old_retrieval_cannot_pass_by_reusing_its_own_timestamp() -> None:
    policy = RiskPolicy(max_price_age=timedelta(hours=48))
    prices = {
        "SPY": {
            "price": Decimal("100"),
            "as_of": RETRIEVED,
            "first_retrieved_at": RETRIEVED,
            "feed": "sip",
            "bar_kind": "daily",
            "realtime_executable": False,
        }
    }
    result = RiskEngine(policy).evaluate(
        _proposal(RETRIEVED),
        InternalLedger(cash_usd=Decimal("100")),
        prices,
        now=TODAY,
    )
    assert result.verdict == "INSUFFICIENT_DATA"
    assert any(
        row.rule == "stale_price" and row.verdict == "INSUFFICIENT_DATA"
        for row in result.rule_verdicts
    )


def _status(result, rule: str) -> str | None:
    for row in result.rule_verdicts:
        if row.rule == rule:
            return row.verdict
    return None


def test_future_quote_is_insufficient_data() -> None:
    future = datetime(2026, 10, 19, 15, 0, tzinfo=UTC)
    result = RiskEngine(RiskPolicy()).evaluate(
        _proposal(TODAY),
        InternalLedger(cash_usd=Decimal("100")),
        {"SPY": {"price": Decimal("100"), "as_of": future, "feed": "sip"}},
        now=TODAY,
    )
    assert result.verdict == "INSUFFICIENT_DATA"
    assert _status(result, "missing_or_invalid_price") == "INSUFFICIENT_DATA"


def test_future_proposal_timestamp_is_insufficient_data() -> None:
    result = RiskEngine(RiskPolicy()).evaluate(
        _proposal(TODAY + timedelta(hours=2)),
        InternalLedger(cash_usd=Decimal("100")),
        {"SPY": {"price": Decimal("100"), "as_of": TODAY, "feed": "sip"}},
        now=TODAY,
    )
    assert result.verdict == "INSUFFICIENT_DATA"
    assert _status(result, "proposal_timestamp") == "INSUFFICIENT_DATA"


def test_naive_quote_timestamp_is_insufficient_data() -> None:
    result = RiskEngine(RiskPolicy()).evaluate(
        _proposal(TODAY),
        InternalLedger(cash_usd=Decimal("100")),
        {"SPY": {"price": Decimal("100"), "as_of": datetime(2026, 10, 16, 15, 0), "feed": "sip"}},
        now=TODAY,
    )
    assert result.verdict == "INSUFFICIENT_DATA"


def test_small_clock_skew_still_allows_a_current_quote() -> None:
    skewed = TODAY + timedelta(seconds=30)
    result = RiskEngine(RiskPolicy()).evaluate(
        _proposal(skewed),
        InternalLedger(cash_usd=Decimal("100")),
        {"SPY": {"price": Decimal("100"), "as_of": TODAY, "feed": "sip"}},
        now=TODAY,
    )
    assert result.verdict == "APPROVE", result.reasons


def test_weekend_observation_is_insufficient_data() -> None:
    saturday = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
    result = RiskEngine(RiskPolicy()).evaluate(
        _proposal(saturday),
        InternalLedger(cash_usd=Decimal("100")),
        {"SPY": {"price": Decimal("100"), "as_of": saturday, "feed": "sip"}},
        now=saturday,
    )
    assert result.verdict == "INSUFFICIENT_DATA"
    assert _status(result, "exchange_session") == "INSUFFICIENT_DATA"


def test_fresh_delayed_daily_bar_is_not_a_live_price_but_can_be_evaluated() -> None:
    market = datetime(2026, 10, 15, 14, 30, tzinfo=UTC)
    prices = {
        "SPY": {
            "price": Decimal("100"),
            "as_of": market,
            "first_retrieved_at": TODAY,
            "session_date": "2026-10-15",
            "feed": "sip",
            "bar_kind": "daily",
            "realtime_executable": False,
        }
    }
    result = RiskEngine(RiskPolicy()).evaluate(
        _proposal(TODAY),
        InternalLedger(cash_usd=Decimal("100")),
        prices,
        now=TODAY,
    )
    assert result.verdict == "APPROVE", result.reasons
    assert _status(result, "delayed_daily_bar") == "PASS"


def test_daily_bar_labeled_realtime_is_insufficient_data() -> None:
    prices = {
        "SPY": {
            "price": Decimal("100"),
            "as_of": TODAY,
            "feed": "sip",
            "bar_kind": "daily",
            "realtime_executable": True,
        }
    }
    result = RiskEngine(RiskPolicy()).evaluate(
        _proposal(TODAY),
        InternalLedger(cash_usd=Decimal("100")),
        prices,
        now=TODAY,
    )
    assert result.verdict == "INSUFFICIENT_DATA"
    assert _status(result, "delayed_daily_bar") == "INSUFFICIENT_DATA"


def test_current_session_observation_is_approved() -> None:
    result = RiskEngine(RiskPolicy()).evaluate(
        _proposal(TODAY),
        InternalLedger(cash_usd=Decimal("100")),
        {"SPY": {"price": Decimal("100"), "as_of": TODAY, "feed": "sip"}},
        now=TODAY,
    )
    assert result.verdict == "APPROVE", result.reasons
