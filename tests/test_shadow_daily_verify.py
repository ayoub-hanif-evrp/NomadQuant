"""Daily inspection stays read-only, and the verifier recomputes evidence."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from nomadquant.shadow.daily import run_daily_operation
from nomadquant.shadow.store import ShadowStore
from nomadquant.shadow.verify import verify_cycle
from tests.conftest import make_settings
from tests.test_shadow_missed_signal import _market


def test_daily_inspect_does_not_sync_or_change_cash(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    ShadowStore(settings.shadow_path, namespace="forward")
    before = ShadowStore(settings.shadow_path, namespace="forward").snapshot()
    code, record = run_daily_operation(settings, mode="inspect", sync=False)
    after = ShadowStore(settings.shadow_path, namespace="forward").snapshot()
    assert code == 0
    assert record["data_sync"]["skipped"] is True
    assert record["operation_id"]
    assert record["worker_run_id"]
    assert after["cash_usd"] == before["cash_usd"] == Decimal("100")
    assert after["holdings"] == {}
    assert after["version"] == before["version"]
    saved = ShadowStore(settings.shadow_path, namespace="forward").list_daily_operations()
    assert saved[0]["operation_id"] == record["operation_id"]


def test_verifier_rejects_a_tampered_evidence_hash(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    market = Path(settings.market_data_path)
    _market(market, date(2019, 11, 1), date(2020, 2, 5))
    shadow = ShadowStore(settings.shadow_path, namespace="forward")
    shadow.set_meta("forward_pilot_started_at", "2020-01-15T00:00:00+00:00")
    from nomadquant.shadow.cycle import run_shadow_cycle

    run_shadow_cycle(
        market_path=market,
        shadow_path=settings.shadow_path,
        risk_path=settings.risk_path,
        mode="apply",
        as_of=datetime(2020, 2, 5, 22, tzinfo=UTC),
    )
    store = ShadowStore(settings.shadow_path, namespace="forward")
    missed = next(row for row in store.list_cycles(limit=10) if row["status"] == "missed_signal")
    honest = verify_cycle(settings, int(missed["id"]))
    assert honest["status"] == "PASS"
    assert honest["verified"] is True
    assert any(
        row["name"] == "missed_not_backfilled" and row["status"] == "PASS"
        for row in honest["checks"]
    )
    with store._connect() as connection:
        connection.execute(
            "UPDATE shadow_cycles SET evidence_hash = ? WHERE id = ?",
            ("tampered", missed["id"]),
        )
    tampered = verify_cycle(settings, int(missed["id"]))
    assert tampered["status"] == "FAIL"
    assert tampered["verified"] is False
