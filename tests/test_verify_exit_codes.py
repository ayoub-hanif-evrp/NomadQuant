"""Verifier CLI exit codes are a shell contract, not only a JSON field."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from nomadquant.marketdata.calendar import sessions_between
from nomadquant.marketdata.store import MarketStore, StoredBar, content_hash
from nomadquant.shadow.store import ShadowStore


def _run(shadow: Path, market: Path, cycle_id: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    env["SHADOW_PATH"] = str(shadow)
    env["MARKET_DATA_PATH"] = str(market)
    env["RISK_PATH"] = str(shadow.with_name("risk.sqlite"))
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from nomadquant.shadow.cli import main; main(['verify','--cycle-id','"
            + cycle_id
            + "'])",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_missing_cycle_exits_invalid_artifact(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow.sqlite"
    ShadowStore(shadow, namespace="forward")
    proc = _run(shadow, tmp_path / "market.sqlite", "4")
    assert proc.returncode == 3
    body = json.loads(proc.stdout)
    assert body["status"] == "INVALID_ARTIFACT"


def test_missing_signal_exits_not_evaluable(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow.sqlite"
    store = ShadowStore(shadow, namespace="forward")
    evidence = {"strategy_id": "spy_tsmom_12_1"}
    _insert(store, evidence=evidence, evidence_hash=_hash(evidence), signal_session=None)
    proc = _run(shadow, tmp_path / "market.sqlite", "1")
    assert proc.returncode == 2
    assert json.loads(proc.stdout)["status"] == "NOT_EVALUABLE"


def test_hash_mismatch_exits_fail(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow.sqlite"
    market = tmp_path / "market.sqlite"
    session = sessions_between(date(2024, 6, 3), date(2024, 6, 3))[0]
    _bar(market, session)
    store = ShadowStore(shadow, namespace="forward")
    evidence = {"strategy_id": "spy_tsmom_12_1", "signal_session": session.isoformat()}
    _insert(
        store, evidence=evidence, evidence_hash="not-the-hash", signal_session=session.isoformat()
    )
    proc = _run(shadow, market, "1")
    assert proc.returncode == 1
    body = json.loads(proc.stdout)
    assert body["status"] == "FAIL"
    assert any(row["name"] == "evidence_hash" and row["status"] == "FAIL" for row in body["checks"])


def _hash(evidence: dict) -> str:
    from nomadquant.shadow.cycle import _hash as cycle_hash

    return cycle_hash(evidence)


def _insert(
    store: ShadowStore, *, evidence: dict, evidence_hash: str, signal_session: str | None
) -> None:
    now = datetime.now(UTC).isoformat()
    ledger = {
        "version": 1,
        "cash_usd": "100",
        "reserved_cash_usd": "0",
        "holdings": {},
        "cost_basis": {},
        "realized_pnl_usd": "0",
        "total_costs_usd": "0",
        "peak_equity_usd": "100",
    }
    with store._connect() as conn:  # noqa: SLF001
        conn.execute(
            """
            INSERT INTO shadow_cycles (
                cycle_key, created_at, mode, label, signal_session, fill_session,
                feed, symbol, status, intent, risk_reasons_json, evidence_json,
                evidence_hash, warnings_json, duration_ms, ledger_before_json,
                ledger_after_json
            ) VALUES (?, ?, 'dry-run', 'forward_shadow', ?, NULL, 'sip', 'SPY',
                      'no_trade', 'no_trade', '[]', ?, ?, '[]', 0, ?, ?)
            """,
            (
                "exit-test",
                now,
                signal_session,
                json.dumps(evidence),
                evidence_hash,
                json.dumps(ledger),
                json.dumps(ledger),
            ),
        )


def _bar(path: Path, session: date) -> None:
    raw = StoredBar(
        symbol="SPY",
        session_date=session,
        timestamp=datetime(session.year, session.month, session.day, 14, 30, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("100"),
        low=Decimal("100"),
        close=Decimal("100"),
        volume=Decimal("1"),
        provider="alpaca",
        feed="sip",
        adjustment="raw",
        timeframe="1Day",
        currency="USD",
        available_at=datetime(session.year, session.month, session.day, 21, 30, tzinfo=UTC),
        first_retrieved_at=datetime(session.year, session.month, session.day, 21, 0, tzinfo=UTC),
        content_hash="pending",
    )
    MarketStore(path).write_bars([StoredBar(**{**raw.__dict__, "content_hash": content_hash(raw)})])
