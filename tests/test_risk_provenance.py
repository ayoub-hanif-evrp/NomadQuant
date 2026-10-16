"""Market time, retrieval time, and availability are checked separately."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nomadquant.marketdata.calendar import is_early_close, is_session
from nomadquant.risk import InternalLedger, Proposal, RiskEngine, RiskPolicy

TODAY = datetime(2026, 6, 15, 18, 0, tzinfo=UTC)


def _eval(quote: dict, *, now: datetime = TODAY, as_of: datetime | None = None):
    return RiskEngine(RiskPolicy()).evaluate(
        Proposal(
            id="prov-1",
            source="test",
            symbol="SPY",
            side="buy",
            quantity=Decimal("0.01"),
            as_of=as_of or now,
        ),
        InternalLedger(cash_usd=Decimal("100")),
        {"SPY": quote},
        now=now,
    )


def _status(result, rule: str) -> str | None:
    for row in result.rule_verdicts:
        if row.rule == rule:
            return row.verdict
    return None


def test_future_retrieval_cannot_hide_behind_a_historical_market_timestamp() -> None:
    market = datetime(2026, 6, 12, 18, 0, tzinfo=UTC)
    result = _eval(
        {
            "price": Decimal("100"),
            "as_of": market,
            "first_retrieved_at": TODAY + timedelta(days=1),
            "session_date": "2026-06-12",
            "feed": "sip",
            "bar_kind": "daily",
            "realtime_executable": False,
        }
    )
    assert result.verdict == "INSUFFICIENT_DATA"
    assert _status(result, "future_retrieval") == "INSUFFICIENT_DATA"


def test_naive_retrieval_is_insufficient() -> None:
    result = _eval(
        {
            "price": Decimal("100"),
            "as_of": TODAY,
            "first_retrieved_at": datetime(2026, 6, 15, 17, 0),
            "feed": "sip",
        }
    )
    assert result.verdict == "INSUFFICIENT_DATA"
    assert _status(result, "retrieval_timestamp") == "INSUFFICIENT_DATA"


def test_session_date_must_match_the_market_timestamp() -> None:
    result = _eval(
        {
            "price": Decimal("100"),
            "as_of": TODAY,
            "session_date": "2026-06-12",
            "feed": "sip",
        }
    )
    assert result.verdict == "INSUFFICIENT_DATA"
    assert _status(result, "session_timestamp") == "INSUFFICIENT_DATA"


def test_unavailable_observation_is_insufficient() -> None:
    result = _eval(
        {
            "price": Decimal("100"),
            "as_of": TODAY - timedelta(hours=2),
            "available_at": TODAY + timedelta(hours=3),
            "feed": "sip",
            "session_date": "2026-06-15",
        }
    )
    assert result.verdict == "INSUFFICIENT_DATA"
    assert _status(result, "observation_availability") == "INSUFFICIENT_DATA"


def test_feed_and_source_must_agree() -> None:
    result = _eval(
        {
            "price": Decimal("100"),
            "as_of": TODAY,
            "feed": "sip",
            "source": "iex",
            "session_date": "2026-06-15",
        }
    )
    assert result.verdict == "INSUFFICIENT_DATA"
    assert _status(result, "feed_provenance") == "INSUFFICIENT_DATA"


def test_holiday_quote_is_insufficient() -> None:
    holiday = datetime(2026, 1, 1, 15, 0, tzinfo=UTC)
    assert is_session(holiday.date()) is False
    result = _eval(
        {"price": Decimal("100"), "as_of": holiday, "feed": "sip"},
        now=holiday,
        as_of=holiday,
    )
    assert result.verdict == "INSUFFICIENT_DATA"


def test_early_close_delayed_daily_can_be_evaluated() -> None:
    early = datetime(2024, 7, 3, 17, 0, tzinfo=UTC)
    assert is_session(early.date())
    assert is_early_close(early.date())
    result = _eval(
        {
            "price": Decimal("100"),
            "as_of": early,
            "first_retrieved_at": early,
            "session_date": "2024-07-03",
            "feed": "sip",
            "bar_kind": "daily",
            "realtime_executable": False,
        },
        now=early,
        as_of=early,
    )
    assert result.verdict == "APPROVE", result.reasons
    assert _status(result, "delayed_daily_bar") == "PASS"


def test_valid_delayed_daily_is_not_real_time() -> None:
    market = datetime(2026, 6, 12, 14, 30, tzinfo=UTC)
    evaluated = datetime(2026, 6, 13, 16, 0, tzinfo=UTC)
    result = _eval(
        {
            "price": Decimal("100"),
            "as_of": market,
            "first_retrieved_at": evaluated,
            "available_at": datetime(2026, 6, 12, 20, 30, tzinfo=UTC),
            "session_date": "2026-06-12",
            "feed": "sip",
            "bar_kind": "daily",
            "realtime_executable": False,
        },
        now=evaluated,
        as_of=evaluated,
    )
    assert result.verdict == "APPROVE", result.reasons
    assert _status(result, "delayed_daily_bar") == "PASS"


def test_standard_time_and_daylight_time_sessions_are_distinct_from_weekends() -> None:
    winter = datetime(2026, 1, 15, 15, 0, tzinfo=UTC)
    summer = datetime(2026, 6, 15, 15, 0, tzinfo=UTC)
    assert is_session(winter.date()) and is_session(summer.date())
    for stamp in (winter, summer):
        result = _eval(
            {
                "price": Decimal("100"),
                "as_of": stamp,
                "feed": "sip",
                "session_date": stamp.date().isoformat(),
            },
            now=stamp,
            as_of=stamp,
        )
        assert result.verdict == "APPROVE", result.reasons
