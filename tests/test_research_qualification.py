"""Corporate-action datasets and locked qualification. Fixtures are not market history."""

import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from nomadquant.marketdata.action_client import download_corporate_actions
from nomadquant.marketdata.actions import (
    ActionStore,
    CorporateAction,
    collect_action_pages,
    derive_closes,
    describe_actions,
    parse_corporate_actions,
)
from nomadquant.marketdata.calendar import sessions_between
from nomadquant.marketdata.store import MarketStore
from nomadquant.research.oos import simulate
from nomadquant.research.qualification import (
    append_qualification_trial,
    qualify_daily_strategies,
)
from tests.conftest import make_settings
from tests.market_bars import seed_closes

WHEN = datetime(2024, 8, 2, 20, tzinfo=UTC)
AS_OF = date(2024, 8, 1)
BEFORE = date(2024, 7, 31)


def test_a_future_split_does_not_change_the_known_price() -> None:
    raw = {"ZZZ": {BEFORE: Decimal("100"), AS_OF: Decimal("51")}}
    original = dict(raw["ZZZ"])
    early = derive_closes(
        raw, [_split(known=BEFORE)], policy="split", timing="announcement", as_of=BEFORE
    )
    later = derive_closes(
        raw, [_split(known=AS_OF)], policy="split", timing="announcement", as_of=AS_OF
    )
    assert raw["ZZZ"] == original
    assert early.usable is True
    assert early.prices["ZZZ"][BEFORE] == Decimal("100")
    assert later.prices["ZZZ"][BEFORE] == Decimal("50")
    assert later.prices["ZZZ"][AS_OF] == Decimal("51")


def test_a_dividend_is_added_on_the_ex_date_only() -> None:
    raw = {"ZZZ": {date(2024, 6, 3): Decimal("100"), date(2024, 6, 4): Decimal("100")}}
    action = _cash(date(2024, 6, 4), Decimal("1"))
    early = derive_closes(
        raw, [action], policy="total_return", timing="announcement", as_of=date(2024, 6, 3)
    )
    later = derive_closes(
        raw, [action], policy="total_return", timing="announcement", as_of=date(2024, 6, 4)
    )
    assert early.prices["ZZZ"][date(2024, 6, 3)] == Decimal("100")
    assert later.prices["ZZZ"][date(2024, 6, 4)] == Decimal("101")


def test_alpaca_process_dates_are_not_point_in_time() -> None:
    payload = {
        "corporate_actions": {
            "cash_dividends": [
                {
                    "id": "div-1",
                    "symbol": "ZZZ",
                    "cusip": "000000000",
                    "rate": "0.50",
                    "special": False,
                    "foreign": False,
                    "process_date": "2024-06-04",
                    "ex_date": "2024-06-04",
                }
            ],
            "forward_splits": [
                {
                    "id": "split-1",
                    "symbol": "ZZZ",
                    "cusip": "000000000",
                    "new_rate": "2",
                    "old_rate": "1",
                    "process_date": "2024-08-01",
                    "ex_date": "2024-08-01",
                }
            ],
        },
        "next_page_token": None,
    }
    parsed, rejected = parse_corporate_actions(payload, retrieved_at=WHEN, source="alpaca")
    assert rejected == 0
    assert all(item.known_at is None for item in parsed)
    raw = {"ZZZ": {date(2024, 6, 4): Decimal("100"), AS_OF: Decimal("50")}}
    evidence = describe_actions(
        parsed,
        raw,
        policy="total_return",
        timing="as_retrieved",
        as_of=AS_OF,
        feed="iex",
        checked=True,
    )
    assert evidence["point_in_time_total_return"] is False
    assert evidence["reason"] == "alpaca_process_date_is_not_an_announcement_time"
    announced = describe_actions(
        parsed,
        raw,
        policy="total_return",
        timing="announcement",
        as_of=AS_OF,
        feed="iex",
        checked=True,
    )
    assert announced["point_in_time_total_return"] is False
    assert announced["reason"] == "action_missing_announcement_time"


def test_a_name_change_blocks_total_return(tmp_path: Path) -> None:
    payload = {
        "corporate_actions": {
            "name_changes": [
                {
                    "id": "name-1",
                    "old_symbol": "ZZZ",
                    "new_symbol": "YYY",
                    "process_date": "2024-06-03",
                }
            ]
        }
    }
    parsed, rejected = parse_corporate_actions(payload, retrieved_at=WHEN, source="alpaca")
    assert rejected == 0
    assert parsed[0].kind == "unmodeled"
    evidence = describe_actions(
        parsed,
        {"ZZZ": {date(2024, 6, 3): Decimal("10")}},
        policy="total_return",
        timing="announcement",
        as_of=date(2024, 6, 3),
        feed="iex",
        checked=True,
    )
    assert evidence["research_state"] == "NOT_EVALUABLE"
    assert evidence["reason"] == "unmodeled_corporate_action"
    store = ActionStore(tmp_path / "market.sqlite")
    store.write(parsed)
    changed = CorporateAction(
        source="alpaca",
        source_id="name-1",
        symbol="YYY",
        kind="unmodeled",
        ex_date=date(2024, 6, 3),
        ratio=None,
        cash_per_share=None,
        process_date=date(2024, 6, 3),
        known_at=None,
        retrieved_at=WHEN,
        raw_hash="different",
    )
    _inserted, unchanged, revisions = store.write([changed])
    assert unchanged == 0
    assert revisions == 1
    assert store.load()[0].symbol == "ZZZ"
    assert store.revision_count() == 1


def test_an_incomplete_page_is_not_stored(tmp_path: Path) -> None:
    def fetch_page(token: str | None) -> dict[str, object]:
        if token is None:
            return {"corporate_actions": {"cash_dividends": []}, "next_page_token": "page-2"}
        raise RuntimeError("down")

    store = ActionStore(tmp_path / "market.sqlite")
    download = download_corporate_actions(store, fetch_page, retrieved_at=WHEN)
    assert download.complete is False
    assert store.load() == []
    repeated = collect_action_pages(
        lambda token: {"corporate_actions": {}, "next_page_token": "again"},
        retrieved_at=WHEN,
        source="alpaca",
        max_pages=3,
    )
    assert repeated.complete is False
    assert repeated.reason == "repeated_page_token"


def test_derived_rows_leave_the_raw_bar_in_place(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    day = date(2024, 6, 3)
    stamp = datetime(2024, 6, 3, 20, tzinfo=UTC)
    seed_closes(settings, {"SPY": {day: Decimal("100")}, "QQQ": {day: Decimal("100")}}, now=stamp)
    evidence = describe_actions(
        [],
        {"SPY": {day: Decimal("100")}, "QQQ": {day: Decimal("100")}},
        policy="total_return",
        timing="announcement",
        as_of=day,
        feed="iex",
        checked=True,
    )
    actions = ActionStore(settings.market_data_path)
    actions.write_derived(
        evidence["derived_prices"],
        feed="iex",
        policy="total_return",
        timing="announcement",
        as_of=day,
        fingerprint=str(evidence["series_fingerprint"]),
        computed_at=stamp,
    )
    raw = MarketStore(settings.market_data_path).session_bar("SPY", "iex", day)
    assert raw is not None
    assert raw.adjustment == "raw"
    assert raw.close == Decimal("100")
    assert actions.derived_close(
        "SPY", day, feed="iex", policy="total_return", timing="announcement", as_of=day
    ) == Decimal("100")
    with sqlite3.connect(settings.market_data_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM bars WHERE adjustment = 'raw'").fetchone()[
            0
        ]
    assert count == 2
    try:
        actions.write_derived(
            evidence["derived_prices"],
            feed="iex",
            policy="raw",
            timing="announcement",
            as_of=day,
            fingerprint="raw",
            computed_at=stamp,
        )
    except ValueError:
        refused = True
    else:
        refused = False
    assert refused is True


def test_the_fill_is_the_session_after_the_signal() -> None:
    sessions = sessions_between(date(2023, 1, 3), date(2024, 1, 12))
    series = {day: Decimal("100") for day in sessions}
    series[sessions[199]] = Decimal("101")
    series[sessions[200]] = Decimal("150")
    for day in sessions[201:]:
        series[day] = Decimal("150")
    prices = {"SPY": series, "QQQ": dict(series)}
    evidence = describe_actions(
        [],
        prices,
        policy="total_return",
        timing="announcement",
        as_of=sessions[-1],
        feed="sip",
        checked=True,
    )
    report = qualify_daily_strategies(evidence["derived_prices"], sessions, evidence=evidence)
    path = simulate(
        evidence["derived_prices"], sessions, spread_bps=Decimal("1"), slippage_bps=Decimal("1")
    )
    assert path.equity[200].equity < Decimal("100")
    assert report["execution"] == "signal_close_fill_next_close"
    assert report["paper_execution"] == "market_order_during_the_session"
    assert report["comparable_to_paper_fills"] is False
    assert report["state"] in {"FAILED", "INCONCLUSIVE", "RESEARCH_QUALIFIED"}
    assert report["permission_to_trade"] is False


def test_locked_gates_can_fail_or_qualify() -> None:
    flat = _series(Decimal("0"), 0, Decimal("0"))
    failed = _qualify(flat)
    assert failed["state"] == "FAILED"
    assert failed["reason"] == "oos_net_return_not_positive"
    assert failed["parameter_refit"] is False
    rising = _series(Decimal("0.20"), 0, Decimal("0"))
    inconclusive = _qualify(rising)
    assert inconclusive["state"] == "INCONCLUSIVE"
    deep = _qualify(_series(Decimal("0.20"), 30, Decimal("0.03")))
    assert deep["state"] == "INCONCLUSIVE"
    assert deep["reason"] == "fold_signs_disagree"
    crash = _series(Decimal("0.20"), 8, Decimal("0.03"))
    qualified = _qualify(crash)
    assert qualified["state"] == "RESEARCH_QUALIFIED"
    assert qualified["reason"] == "primary_cleared_locked_gates"
    assert qualified["permission_to_trade"] is False
    assert Decimal(qualified["metrics"]["net_return"]) > Decimal(
        qualified["benchmarks"]["spy_buy_hold_matched"]
    )


def test_trials_keep_the_failed_result(tmp_path: Path) -> None:
    report = _qualify(_series(Decimal("0"), 0, Decimal("0")))
    path = tmp_path / "research.sqlite"
    append_qualification_trial(path, report)
    append_qualification_trial(path, report)
    with sqlite3.connect(path) as connection:
        rows = connection.execute("SELECT state FROM qualification_trials").fetchall()
    assert [row[0] for row in rows] == ["FAILED", "FAILED"]


def _qualify(prices: tuple[list[date], dict[str, dict[date, Decimal]]]) -> dict[str, object]:
    sessions, series = prices
    evidence = describe_actions(
        [],
        series,
        policy="total_return",
        timing="announcement",
        as_of=sessions[-1],
        feed="iex",
        checked=True,
    )
    tampered = {symbol: dict(rows) for symbol, rows in series.items()}
    tampered["SPY"][sessions[0]] = Decimal("1")
    mismatch = qualify_daily_strategies(tampered, sessions, evidence=evidence)
    assert mismatch["state"] == "NOT_EVALUABLE"
    assert mismatch["reason"] == "dataset_fingerprint_mismatch"
    return qualify_daily_strategies(evidence["derived_prices"], sessions, evidence=evidence)


def _series(
    step: Decimal, crash_days: int, crash: Decimal
) -> tuple[list[date], dict[str, dict[date, Decimal]]]:
    sessions = sessions_between(date(2022, 1, 3), date(2024, 6, 28))
    price = Decimal("100")
    crash_at = len(sessions) - crash_days
    series = {}
    for index, day in enumerate(sessions):
        if crash_days and index >= crash_at:
            price *= Decimal("1") - crash
        else:
            price += step
        series[day] = price
    return sessions, {"SPY": series, "QQQ": dict(series)}


def _split(known: date) -> CorporateAction:
    return CorporateAction(
        source="fixture",
        source_id="split-1",
        symbol="ZZZ",
        kind="forward_split",
        ex_date=AS_OF,
        ratio=Decimal("2"),
        cash_per_share=None,
        process_date=AS_OF,
        known_at=datetime(known.year, known.month, known.day, tzinfo=UTC),
        retrieved_at=WHEN,
        raw_hash="split",
    )


def _cash(ex_date: date, amount: Decimal) -> CorporateAction:
    return CorporateAction(
        source="fixture",
        source_id="div-1",
        symbol="ZZZ",
        kind="cash_dividend",
        ex_date=ex_date,
        ratio=None,
        cash_per_share=amount,
        process_date=ex_date,
        known_at=datetime(ex_date.year, ex_date.month, ex_date.day, tzinfo=UTC),
        retrieved_at=WHEN,
        raw_hash="div",
    )
