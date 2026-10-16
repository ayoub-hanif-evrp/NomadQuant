"""Bounded deception checks and the versioned cost-addback metric."""

from datetime import date, timedelta
from decimal import Decimal

from nomadquant.research.audit import audit_series
from nomadquant.research.metrics import GROSS_RETURN_DEFINITION, METRIC_METHOD, compute_metrics
from nomadquant.research.models import EquityPoint


def _series(n: int, price: str = "100") -> tuple[dict[date, Decimal], list[date]]:
    start = date(2018, 1, 2)
    sessions = [start + timedelta(days=index) for index in range(n)]
    closes = {session: Decimal(price) for session in sessions}
    return closes, sessions


def test_future_bar_and_prefix_do_not_change_a_stable_signal() -> None:
    closes, sessions = _series(300)
    decision = sessions[280]
    checks = audit_series(
        closes,
        sessions,
        lookback=20,
        skip=5,
        decision_sessions=[decision],
        fill_sessions=[sessions[281]],
    )
    by_name = {row["name"]: row["status"] for row in checks}
    assert by_name["future_bars_do_not_change_past_signal"] == "PASS"
    assert by_name["prefix_preserves_signal"] == "PASS"
    assert by_name["identical_inputs"] == "PASS"
    assert by_name["same_close_fill_forbidden"] == "PASS"
    assert by_name["unsafe_prices"] == "PASS"
    assert by_name["missing_bar_fails_closed"] == "PASS"
    assert by_name["revision_changes_fingerprint"] == "PASS"
    assert by_name["cost_sensitivity_explained"] == "PASS"
    assert by_name["adjustment_evidence"] == "NOT_EVALUABLE"
    assert all(row["status"] != "FAIL" for row in checks)


def test_same_session_fill_is_rejected() -> None:
    closes, sessions = _series(80)
    decision = sessions[70]
    checks = audit_series(
        closes,
        sessions,
        lookback=10,
        skip=2,
        decision_sessions=[decision],
        fill_sessions=[decision],
    )
    assert any(
        row["name"] == "same_close_fill_forbidden" and row["status"] == "FAIL" for row in checks
    )


def test_gross_return_is_a_cost_addback_not_a_cost_free_replay() -> None:
    points = [
        EquityPoint(
            session_date=date(2024, 1, 2),
            equity=Decimal("90"),
            cash=Decimal("90"),
            exposure=Decimal("0"),
            drawdown=Decimal("0.5"),
            window="test",
        ),
        EquityPoint(
            session_date=date(2024, 1, 3),
            equity=Decimal("110"),
            cash=Decimal("110"),
            exposure=Decimal("0"),
            drawdown=Decimal("0"),
            window="test",
        ),
    ]
    metrics = compute_metrics(
        window="test",
        equity=points,
        trades=[],
        start_capital=Decimal("100"),
        opening_equity=Decimal("100"),
    )
    assert metrics.metric_method == METRIC_METHOD
    assert "not a separately replayed" in metrics.gross_return_definition
    assert metrics.gross_return_definition == GROSS_RETURN_DEFINITION
    assert metrics.cost_free_return is None
    assert "cost_free_replay_not_run" in metrics.unavailable
    assert metrics.net_return == Decimal("0.10")
    assert metrics.max_drawdown == Decimal("0.10")
