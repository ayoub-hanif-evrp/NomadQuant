"""Daily inspection stays read-only, and the verifier recomputes evidence."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from nomadquant.shadow.daily import run_daily_operation
from nomadquant.shadow.pilot import forward_pilot_report
from nomadquant.shadow.store import ShadowStore
from nomadquant.shadow.verify import verify_cycle
from tests.conftest import make_settings
from tests.shadow_support import grant_forward_approval
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


def test_inspect_sync_records_the_download_and_does_not_trade(
    tmp_path: Path, monkeypatch: object
) -> None:
    def _sync(settings: object, *, feed: str = "sip") -> dict[str, object]:
        assert feed == "sip"
        return {"sync": "noop", "inserted": 0, "broker_orders": False}

    monkeypatch.setattr("nomadquant.shadow.daily.data_sync", _sync)  # type: ignore[attr-defined]
    settings = make_settings(tmp_path)
    ShadowStore(settings.shadow_path, namespace="forward")
    code, record = run_daily_operation(settings, mode="inspect", sync=True)
    after = ShadowStore(settings.shadow_path, namespace="forward").snapshot()
    assert code == 0
    assert record["mode"] == "inspect"
    assert record["data_sync"]["sync"] == "noop"
    assert record["data_sync"]["inserted"] == 0
    assert after["cash_usd"] == Decimal("100")
    assert after["holdings"] == {}


def test_verifier_rejects_a_tampered_evidence_hash(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    market = Path(settings.market_data_path)
    _market(market, date(2019, 11, 1), date(2020, 2, 5))
    shadow = ShadowStore(settings.shadow_path, namespace="forward")
    shadow.set_meta("forward_pilot_started_at", "2020-01-15T00:00:00+00:00")
    from nomadquant.shadow.cycle import run_shadow_cycle

    as_of = datetime(2020, 2, 5, 22, tzinfo=UTC)
    grant_forward_approval(Path(settings.shadow_path), market, as_of)
    run_shadow_cycle(
        market_path=market,
        shadow_path=settings.shadow_path,
        risk_path=settings.risk_path,
        mode="apply",
        as_of=as_of,
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


def test_verifier_scopes_do_not_pass_a_missing_cutoff_or_a_no_fill(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    market = Path(settings.market_data_path)
    _market(market, date(2019, 11, 1), date(2020, 2, 5))
    shadow = ShadowStore(settings.shadow_path, namespace="forward")
    shadow.set_meta("forward_pilot_started_at", "2020-01-15T00:00:00+00:00")
    from nomadquant.shadow.cycle import run_shadow_cycle

    as_of = datetime(2020, 2, 5, 22, tzinfo=UTC)
    grant_forward_approval(Path(settings.shadow_path), market, as_of)
    run_shadow_cycle(
        market_path=market,
        shadow_path=settings.shadow_path,
        risk_path=settings.risk_path,
        mode="apply",
        as_of=as_of,
    )
    store = ShadowStore(settings.shadow_path, namespace="forward")
    missed = next(row for row in store.list_cycles(limit=10) if row["status"] == "missed_signal")
    report = verify_cycle(settings, int(missed["id"]))
    assert report["scopes"]["full_cycle"] == "PASS"
    assert any(
        row["name"] == "fill_assumption" and row["status"] == "NOT_APPLICABLE"
        for row in report["checks"]
    )
    evidence = dict(missed["evidence"])
    evidence["signal_available_at"] = "1999-01-01T00:00:00+00:00"
    after = dict(missed["ledger_after"])
    after["cash_usd"] = "50"
    with store._connect() as connection:
        connection.execute(
            "UPDATE shadow_cycles SET evidence_json = ?, ledger_after_json = ? WHERE id = ?",
            (json.dumps(evidence), json.dumps(after), missed["id"]),
        )
    cutoff = verify_cycle(settings, int(missed["id"]))
    by_name = {row["name"]: row["status"] for row in cutoff["checks"]}
    assert by_name["information_cutoff"] == "FAIL"
    assert by_name["cash_unchanged_without_fill"] == "FAIL"
    assert by_name["evidence_hash"] == "FAIL"
    assert cutoff["verified"] is False


def test_pilot_report_is_inconclusive_without_a_fill(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    assert forward_pilot_report(settings)["initialized"] is False
    assert not Path(settings.shadow_path).exists()
    market = Path(settings.market_data_path)
    _market(market, date(2019, 11, 1), date(2020, 2, 5))
    shadow = ShadowStore(settings.shadow_path, namespace="forward")
    shadow.set_meta("forward_pilot_started_at", "2020-01-15T00:00:00+00:00")
    from nomadquant.shadow.cycle import run_shadow_cycle

    as_of = datetime(2020, 2, 5, 22, tzinfo=UTC)
    grant_forward_approval(Path(settings.shadow_path), market, as_of)
    run_shadow_cycle(
        market_path=market,
        shadow_path=settings.shadow_path,
        risk_path=settings.risk_path,
        mode="apply",
        as_of=as_of,
    )
    report = forward_pilot_report(settings, verify_limit=3)
    assert report["hypothetical_fills"] == 0
    assert report["status"] == "INCONCLUSIVE"
    assert report["sessions_missed"] >= 1
    assert report["hypothesis"]["comparison"] == "inconclusive"
    assert report["baseline"]["comparable_to_shadow_fills"] is False
    assert report["cash_usd"] == "100"
