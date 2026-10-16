"""Bounded checks that a research path did not quietly use the future.

A sampled audit is not comprehensive proof. Coverage is reported on every result.
Corporate-action and dividend histories are not invented.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from nomadquant.finance.execution import execution_price
from nomadquant.marketdata.store import MarketStore, content_hash
from nomadquant.research.models import CostModel, ExperimentConfig
from nomadquant.research.signals import momentum_return
from nomadquant.research.store import ResearchStore

_SAMPLE_LIMIT = 5
_COSTS = CostModel()


def audit_run(
    run_id: int,
    *,
    research_path: str | Path,
    market_path: str | Path,
    sample_limit: int = _SAMPLE_LIMIT,
) -> dict[str, Any]:
    store = ResearchStore(research_path)
    run = store.get_run(run_id)
    if run is None:
        return _report(run_id, [], sample_limit, 0, "INVALID_ARTIFACT", "run was not found")
    try:
        config = ExperimentConfig.model_validate(run["config"])
    except ValueError as exc:
        return _report(run_id, [], sample_limit, 0, "INVALID_ARTIFACT", str(exc))
    market = MarketStore.open_readonly(market_path)
    symbol = config.symbols[0]
    if market is None or not market.has_symbol(symbol, config.feed):
        return _report(run_id, [], sample_limit, 0, "INVALID_ARTIFACT", "market bars are absent")
    sessions = sorted(market.sessions(symbol, config.feed))
    closes = {
        session: close
        for session, _o, _h, _l, close in market.session_ohlc(
            symbol, config.feed, sessions[0], sessions[-1]
        )
    }
    decisions = [
        row
        for row in store.decisions(run_id, strategy_id=config.strategy_id)
        if row.get("signal") == "tsmom_rebalance" and row.get("session_date")
    ]
    sample = decisions[:sample_limit]
    checks = audit_series(
        closes,
        sessions,
        lookback=config.lookback_sessions,
        skip=config.skip_sessions,
        decision_sessions=[date.fromisoformat(str(row["session_date"])) for row in sample],
        fill_sessions=[
            None if not row.get("fill_session") else date.fromisoformat(str(row["fill_session"]))
            for row in sample
        ],
    )
    coverage = len(sample)
    comprehensive = coverage == len(decisions) and coverage > 0
    status = _status(checks)
    return _report(
        run_id,
        checks,
        sample_limit,
        coverage,
        status,
        "sampled prefix audit; not comprehensive proof"
        if not comprehensive
        else "sample covers every stored decision",
        comprehensive=comprehensive,
        decision_count=len(decisions),
    )


def audit_series(
    closes: dict[date, Decimal],
    sessions: list[date],
    *,
    lookback: int,
    skip: int,
    decision_sessions: list[date],
    fill_sessions: list[date | None] | None = None,
) -> list[dict[str, str]]:
    """Run the deception checks. ``decision_sessions`` is the bounded sample."""
    checks: list[dict[str, str]] = []
    fills = fill_sessions or [None] * len(decision_sessions)
    if not decision_sessions:
        checks.append(_check("sample", "NOT_EVALUABLE", "no decisions were supplied"))
    stable: list[Decimal | None] = []
    for session, fill_session in zip(decision_sessions, fills, strict=False):
        original = momentum_return(closes, sessions, session, lookback, skip)
        future_sessions = [*sessions, date(2099, 1, 2)]
        future_closes = {**closes, date(2099, 1, 2): Decimal("999999")}
        appended = momentum_return(future_closes, future_sessions, session, lookback, skip)
        truncated_sessions = [item for item in sessions if item <= session]
        truncated_closes = {item: closes[item] for item in truncated_sessions if item in closes}
        truncated = momentum_return(truncated_closes, truncated_sessions, session, lookback, skip)
        again = momentum_return(closes, sessions, session, lookback, skip)
        stable.append(original)
        checks.append(
            _check(
                "future_bars_do_not_change_past_signal",
                "PASS" if original == appended else "FAIL",
                session.isoformat(),
            )
        )
        checks.append(
            _check(
                "prefix_preserves_signal",
                "PASS" if original == truncated else "FAIL",
                session.isoformat(),
            )
        )
        checks.append(
            _check(
                "identical_inputs",
                "PASS" if original == again else "FAIL",
                session.isoformat(),
            )
        )
        same_close = fill_session is not None and fill_session <= session
        checks.append(
            _check(
                "same_close_fill_forbidden",
                "FAIL" if same_close else "PASS",
                "momentum fills must use a later session",
            )
        )
    needed = lookback + skip + 1
    if len(sessions) > needed:
        as_of = sessions[-1]
        full = momentum_return(closes, sessions, as_of, lookback, skip)
        tail = sessions[-needed:]
        tail_closes = {item: closes[item] for item in tail if item in closes}
        short = momentum_return(tail_closes, tail, as_of, lookback, skip)
        checks.append(
            _check(
                "warmup_stability",
                "PASS" if full == short else "FAIL",
                "history before the warm-up window does not change the signal",
            )
        )
    else:
        checks.append(
            _check("warmup_stability", "NOT_EVALUABLE", "series is shorter than the warm-up")
        )
    if sessions:
        end_index = len(sessions) - 1 - skip
        start_index = end_index - lookback
        hole = dict(closes)
        if 0 <= start_index < len(sessions):
            hole.pop(sessions[start_index], None)
        missing = momentum_return(hole, sessions, sessions[-1], lookback, skip)
        checks.append(
            _check(
                "missing_bar_fails_closed",
                "PASS" if missing is None else "FAIL",
                "a removed close must not still produce a target",
            )
        )
    bad = _bad_prices(closes, sessions, lookback, skip)
    checks.append(bad)
    checks.append(_revision_check())
    checks.append(_discontinuity_check(closes, sessions))
    cheap = execution_price(Decimal("100"), _COSTS, side="buy")
    costly = execution_price(
        Decimal("100"),
        CostModel(spread_bps=Decimal("10"), slippage_bps=Decimal("10")),
        side="buy",
    )
    checks.append(
        _check(
            "cost_sensitivity_explained",
            "PASS" if costly > cheap else "FAIL",
            f"1bp buy {cheap} vs 10bp buy {costly}; higher costs raise the buy price",
        )
    )
    checks.append(
        _check(
            "adjustment_evidence",
            "NOT_EVALUABLE",
            "No point-in-time split or dividend file is stored. Raw prices stay unresolved.",
        )
    )
    return checks


def _bad_prices(
    closes: dict[date, Decimal], sessions: list[date], lookback: int, skip: int
) -> dict[str, str]:
    if not sessions:
        return _check("unsafe_prices", "NOT_EVALUABLE", "no sessions")
    as_of = sessions[-1]
    end_index = len(sessions) - 1 - skip
    start_index = end_index - lookback
    target = sessions[start_index] if 0 <= start_index < len(sessions) else sessions[0]

    def poisoned(value: Decimal) -> Decimal | None:
        series = dict(closes)
        series[target] = value
        return momentum_return(series, sessions, as_of, lookback, skip)

    zero = poisoned(Decimal("0"))
    negative = poisoned(Decimal("-1"))
    nan = poisoned(Decimal("NaN"))
    infinity = poisoned(Decimal("Infinity"))
    safe = all(item is None for item in (zero, negative, nan, infinity))
    return _check(
        "unsafe_prices",
        "PASS" if safe else "FAIL",
        "zero, negative, NaN, and Infinity closes do not produce a momentum target",
    )


def _revision_check() -> dict[str, str]:
    from datetime import UTC, datetime

    from nomadquant.marketdata.store import StoredBar

    def bar(close: str) -> StoredBar:
        raw = StoredBar(
            symbol="SPY",
            session_date=date(2024, 1, 2),
            timestamp=datetime(2024, 1, 2, tzinfo=UTC),
            open=Decimal(close),
            high=Decimal(close),
            low=Decimal(close),
            close=Decimal(close),
            volume=Decimal("1"),
            provider="alpaca",
            feed="sip",
            adjustment="raw",
            timeframe="1Day",
            currency="USD",
            available_at=datetime(2024, 1, 2, 21, tzinfo=UTC),
            first_retrieved_at=datetime(2024, 1, 3, tzinfo=UTC),
            content_hash="pending",
        )
        return StoredBar(**{**raw.__dict__, "content_hash": content_hash(raw)})

    changed = content_hash(bar("100")) != content_hash(bar("101"))
    return _check(
        "revision_changes_fingerprint",
        "PASS" if changed else "FAIL",
        "a revised close changes the bar fingerprint",
    )


def _discontinuity_check(closes: dict[date, Decimal], sessions: list[date]) -> dict[str, str]:
    ratios = []
    previous: Decimal | None = None
    for session in sessions:
        price = closes.get(session)
        if price is None or previous is None or previous <= 0:
            previous = price
            continue
        ratios.append(price / previous)
        previous = price
    jump = any(ratio >= Decimal("1.5") or ratio <= Decimal("0.67") for ratio in ratios)
    if not jump:
        return _check(
            "corporate_action_discontinuity",
            "NOT_EVALUABLE",
            "No large raw-price jump in this sample. Split treatment is still unresolved.",
        )
    return _check(
        "corporate_action_discontinuity",
        "NOT_EVALUABLE",
        "A large raw-price jump is visible and is not treated as profit.",
    )


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def _status(checks: list[dict[str, str]]) -> str:
    statuses = {row["status"] for row in checks}
    if "FAIL" in statuses:
        return "FAIL"
    if "INVALID_ARTIFACT" in statuses:
        return "INVALID_ARTIFACT"
    if not checks or "NOT_EVALUABLE" in statuses:
        return "NOT_EVALUABLE"
    return "PASS"


def _report(
    run_id: int,
    checks: list[dict[str, str]],
    sample_limit: int,
    coverage: int,
    status: str,
    note: str,
    *,
    comprehensive: bool = False,
    decision_count: int = 0,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "status": status,
        "comprehensive": comprehensive,
        "sample_limit": sample_limit,
        "sample_coverage": coverage,
        "decision_count": decision_count,
        "checks": checks,
        "note": note,
    }
