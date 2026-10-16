"""Prompt 13: blocked preflight and failed reconcile must not mutate the ledger."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from nomadquant.shadow.store import ShadowStore
from nomadquant.shadow.worker import run_daily_worker
from tests.conftest import make_settings


def test_blocked_preflight_does_not_run_cycle_or_mutate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_settings(tmp_path)
    store = ShadowStore(settings.shadow_path, namespace="forward")
    before = store.snapshot()
    calls: list[str] = []

    monkeypatch.setattr(
        "nomadquant.shadow.gate.run_preflight",
        lambda _settings, **_kwargs: {"status": "BLOCKED", "checks": []},
    )
    monkeypatch.setattr(
        "nomadquant.shadow.gate.run_reconcile",
        lambda _settings: {"ok": True, "issues": [], "recovery_required": False},
    )

    def _cycle(**_kwargs: object) -> dict[str, object]:
        calls.append("cycle")
        return {"status": "filled"}

    monkeypatch.setattr("nomadquant.shadow.worker.run_shadow_cycle", _cycle)

    code, outcome = run_daily_worker(settings, mode="shadow-apply", data_dir=tmp_path)
    after = ShadowStore(settings.shadow_path, namespace="forward").snapshot()
    assert calls == []
    assert outcome["cycle"] is None
    assert outcome["worker_status"] == "FAILED"
    assert code == 1
    assert after["version"] == before["version"]
    assert after["cash_usd"] == before["cash_usd"]
    assert after["holdings"] == before["holdings"]
    assert after["reserved_cash_usd"] == Decimal("0")


def test_failed_reconcile_blocks_shadow_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_settings(tmp_path)
    store = ShadowStore(settings.shadow_path, namespace="forward")
    before_version = store.snapshot()["version"]
    calls: list[str] = []

    monkeypatch.setattr(
        "nomadquant.shadow.gate.run_preflight",
        lambda _settings, **_kwargs: {"status": "READY", "checks": []},
    )
    monkeypatch.setattr(
        "nomadquant.shadow.gate.run_reconcile",
        lambda _settings: {
            "ok": False,
            "issues": ["recovery_required"],
            "recovery_required": True,
        },
    )
    monkeypatch.setattr(
        "nomadquant.shadow.worker.run_shadow_cycle",
        lambda **_kwargs: calls.append("cycle") or {"status": "filled"},
    )

    code, outcome = run_daily_worker(settings, mode="shadow-apply", data_dir=tmp_path)
    after = ShadowStore(settings.shadow_path, namespace="forward").snapshot()
    assert calls == []
    assert outcome["cycle"] is None
    assert outcome["worker_status"] in {"FAILED", "RECOVERY_REQUIRED"}
    assert code in {1, 2}
    assert after["version"] == before_version


def test_recovery_required_blocks_new_fill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path)
    store = ShadowStore(settings.shadow_path, namespace="forward")
    store.reserve_cash(
        intent_id="stuck-1",
        amount=Decimal("5"),
        expected_version=1,
        cycle_key="ck-stuck",
    )
    version = store.snapshot()["version"]
    calls: list[str] = []
    monkeypatch.setattr(
        "nomadquant.shadow.worker.run_shadow_cycle",
        lambda **_kwargs: calls.append("cycle") or {"status": "filled"},
    )
    code, outcome = run_daily_worker(settings, mode="shadow-apply", data_dir=tmp_path)
    after = ShadowStore(settings.shadow_path, namespace="forward").snapshot()
    assert calls == []
    assert outcome["worker_status"] == "RECOVERY_REQUIRED"
    assert code == 2
    assert after["version"] == version
    assert after["reserved_cash_usd"] == Decimal("5")


def test_post_apply_reconcile_failure_is_not_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_settings(tmp_path)
    ShadowStore(settings.shadow_path, namespace="forward")
    monkeypatch.setattr(
        "nomadquant.shadow.gate.run_preflight",
        lambda _settings, **_kwargs: {"status": "READY", "checks": []},
    )
    monkeypatch.setattr(
        "nomadquant.shadow.gate.run_reconcile",
        lambda _settings: {"ok": True, "issues": [], "recovery_required": False},
    )
    monkeypatch.setattr(
        "nomadquant.shadow.worker.run_shadow_cycle",
        lambda **_kwargs: {"status": "filled"},
    )
    monkeypatch.setattr(
        "nomadquant.shadow.worker.run_reconcile",
        lambda _settings: {"ok": False, "issues": ["equity_mismatch"], "recovery_required": False},
    )
    code, outcome = run_daily_worker(settings, mode="shadow-apply", data_dir=tmp_path)
    assert outcome["worker_status"] == "FAILED"
    assert outcome["error"] == "post_apply_reconcile_failed"
    assert code == 1
    assert outcome["reconcile_after"]["ok"] is False
