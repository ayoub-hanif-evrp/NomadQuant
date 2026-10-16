"""Pilot totals come from the whole ledger, not the first 500 rows."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from nomadquant.config import Settings
from nomadquant.shadow.pilot import forward_pilot_report
from nomadquant.shadow.store import ShadowStore


def test_more_than_500_cycles_are_counted(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow.sqlite"
    store = ShadowStore(shadow, namespace="forward")
    now = datetime(2026, 6, 1, tzinfo=UTC).isoformat()
    ledger = json.dumps(
        {
            "version": 1,
            "cash_usd": "100",
            "reserved_cash_usd": "0",
            "holdings": {},
            "cost_basis": {},
            "realized_pnl_usd": "0",
            "total_costs_usd": "0",
            "peak_equity_usd": "100",
        }
    )
    with store._connect() as conn:  # noqa: SLF001
        conn.executemany(
            """
            INSERT INTO shadow_cycles (
                cycle_key, created_at, mode, label, signal_session, feed, symbol,
                status, intent, risk_reasons_json, evidence_json, evidence_hash,
                warnings_json, duration_ms, ledger_before_json, ledger_after_json
            ) VALUES (?, ?, 'dry-run', 'forward_shadow', '2026-06-01', 'sip', 'SPY',
                      ?, 'no_trade', '[]', '{}', 'hash', '[]', 0, ?, ?)
            """,
            [
                (f"cycle-{index}", now, "filled" if index < 40 else "no_trade", ledger, ledger)
                for index in range(520)
            ],
        )
    settings = Settings(
        market_data_path=str(tmp_path / "missing-market.sqlite"),
        shadow_path=str(shadow),
        risk_path=str(tmp_path / "risk.sqlite"),
    )
    report = forward_pilot_report(settings, verify_limit=5)
    assert report["history_totals"]["cycles_total"] == 520
    assert report["hypothetical_fills"] == 40
    assert report["verification_sample"]["checked"] <= 5
    assert report["verification_sample"]["history_cycles"] == 520
    assert "recent sample" in report["verification_sample"]["note"]
