"""Offline shadow portfolio and cycle tests. No broker, no network."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from nomadquant.execution import DryRunExecutionGateway, ExecutionRequest
from nomadquant.marketdata.calendar import sessions_between
from nomadquant.shadow.cycle import LABEL_FORWARD, LABEL_RETRO, run_shadow_cycle
from nomadquant.shadow.store import ShadowStore, ShadowStoreError
from tests.test_research import _fill_market


def _market(tmp: Path) -> Path:
    # Enough history for 252+21 lookback around 2020-ish month starts.
    sessions = sessions_between(date(2019, 1, 2), date(2020, 6, 30))
    closes = [str(100 + (i % 9)) for i in range(len(sessions))]
    path = tmp / "market.sqlite"
    _fill_market(path, sessions, closes)
    return path


def test_empty_ledger_starts_at_100(tmp_path: Path) -> None:
    store = ShadowStore(tmp_path / "shadow.sqlite")
    snap = store.snapshot()
    assert snap["cash_usd"] == Decimal("100")
    assert snap["holdings"] == {}
    assert snap["starting_capital_usd"] == Decimal("100")


def test_dry_run_cycle_does_not_mutate_ledger(tmp_path: Path) -> None:
    market = _market(tmp_path)
    shadow = tmp_path / "shadow.sqlite"
    risk = tmp_path / "risk.sqlite"
    # Use a known month-start in the fixture window.
    signal = date(2020, 3, 2)
    before = ShadowStore(shadow).snapshot()
    result = run_shadow_cycle(
        market_path=market,
        shadow_path=shadow,
        risk_path=risk,
        mode="dry-run",
        signal_session=signal,
        label=LABEL_RETRO,
        as_of=datetime(2020, 6, 1, tzinfo=UTC),
    )
    after = ShadowStore(shadow).snapshot()
    assert after["cash_usd"] == before["cash_usd"]
    assert after["holdings"] == before["holdings"]
    assert result["mode"] == "dry-run"
    assert result["label"] == LABEL_RETRO
    assert "alpaca" not in str(result).lower() or "not" in str(result).lower()


def test_duplicate_cycle_key_is_idempotent(tmp_path: Path) -> None:
    market = _market(tmp_path)
    shadow = tmp_path / "shadow.sqlite"
    risk = tmp_path / "risk.sqlite"
    signal = date(2020, 3, 2)
    kwargs = dict(
        market_path=market,
        shadow_path=shadow,
        risk_path=risk,
        mode="apply",
        signal_session=signal,
        label=LABEL_RETRO,
        as_of=datetime(2020, 6, 1, tzinfo=UTC),
    )
    first = run_shadow_cycle(**kwargs)
    second = run_shadow_cycle(**kwargs)
    assert first["id"] == second["id"]
    assert ShadowStore(shadow).count_cycles() == 1


def test_dry_run_gateway_never_sets_broker_order() -> None:
    gateway = DryRunExecutionGateway(allow_order_submission=False)
    result = gateway.submit(
        ExecutionRequest(
            idempotency_key="k1",
            symbol="SPY",
            side="buy",
            quantity=Decimal("0.01"),
            proposal_id="p1",
            risk_verdict="APPROVE",
            reserved_cash_usd=Decimal("5"),
            policy_hash="abc",
        )
    )
    assert result.is_broker_order is False
    assert result.broker_order_id is None
    assert result.status == "dry_run_accepted"
    with pytest.raises(ValueError):
        DryRunExecutionGateway(allow_order_submission=True)


def test_shadow_store_rejects_duplicate_apply(tmp_path: Path) -> None:
    store = ShadowStore(tmp_path / "shadow.sqlite")
    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "mode": "dry-run",
        "label": LABEL_FORWARD,
        "feed": "sip",
        "symbol": "SPY",
        "status": "no_trade",
        "intent": "hold",
        "evidence": {},
        "evidence_hash": "a" * 64,
        "warnings": [],
        "duration_ms": 1,
        "ledger_before": {"cash_usd": "100", "holdings": {}},
        "ledger_after": {"cash_usd": "100", "holdings": {}},
    }
    store.apply_cycle(cycle_key="k", payload=payload, ledger_after=None, equity_point=None)
    with pytest.raises(ShadowStoreError):
        store.apply_cycle(cycle_key="k", payload=payload, ledger_after=None, equity_point=None)
