"""Supervised daily shadow procedure. Inspection is the default.

Sync and shadow-apply stay opt-in. This module never submits broker orders.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nomadquant.config import Settings
from nomadquant.shadow.data_ops import data_check, data_sync
from nomadquant.shadow.gate import application_guard
from nomadquant.shadow.preflight import run_preflight, run_reconcile
from nomadquant.shadow.store import ShadowStore
from nomadquant.shadow.worker import run_daily_worker

_MODES = {"inspect", "dry-run", "shadow-apply"}


def run_daily_operation(
    settings: Settings,
    *,
    mode: str = "inspect",
    sync: bool = False,
    feed: str = "sip",
    timeout_s: float = 120,
) -> tuple[int, dict[str, Any]]:
    """Run one linked daily operation. ``sync`` and ``shadow-apply`` are explicit."""
    if mode not in _MODES:
        raise ValueError(f"Unknown daily mode {mode!r}.")
    started = datetime.now(UTC)
    operation_id = uuid.uuid4().hex
    record: dict[str, Any] = {
        "operation_id": operation_id,
        "started_at": started.isoformat(),
        "mode": mode,
        "sync_requested": sync,
        "feed": feed,
        "status": "RUNNING",
        "trading_state": "SHADOW_ONLY",
        "allow_order_submission": False,
    }
    deadline = started.timestamp() + timeout_s

    def _step(name: str, fn: Any) -> Any:
        if datetime.now(UTC).timestamp() > deadline:
            raise TimeoutError(f"daily operation exceeded {timeout_s}s before {name}")
        value = fn()
        record[name] = value
        return value

    code = 1
    try:
        _step("data_check", lambda: data_check(settings, feed=feed))
        if sync:
            _step("data_sync", lambda: data_sync(settings, feed=feed))
        else:
            record["data_sync"] = {"skipped": True, "reason": "sync_not_requested"}
        _step("coverage", lambda: data_check(settings, feed=feed))
        _step("preflight", lambda: run_preflight(settings))
        _step("reconcile_before", lambda: run_reconcile(settings))
        if mode == "shadow-apply":
            guard = application_guard(settings)
            record["gate"] = {
                "allowed": guard["allowed"],
                "reasons": guard["reasons"],
            }
            if not guard["allowed"]:
                record["status"] = "BLOCKED"
                record["worker"] = None
                code = 1
                return _finish(settings, record, code)
        worker_mode = "inspect" if mode == "inspect" else mode
        code, outcome = run_daily_worker(settings, mode=worker_mode)  # type: ignore[arg-type]
        record["worker"] = outcome
        record["worker_run_id"] = outcome.get("run_id")
        _step("reconcile_after", lambda: run_reconcile(settings))
        after_ok = bool(record["reconcile_after"].get("ok"))
        worker_status = str((record.get("worker") or {}).get("worker_status", ""))
        if mode == "shadow-apply" and not after_ok:
            record["status"] = "FAILED"
            code = 1
        elif worker_status == "FAILED":
            record["status"] = "FAILED"
        elif worker_status == "RECOVERY_REQUIRED":
            record["status"] = "RECOVERY_REQUIRED"
            code = 2
        else:
            record["status"] = "COMPLETED"
            code = 0 if code == 0 else code
    except TimeoutError as exc:
        record["status"] = "FAILED"
        record["error"] = str(exc)
        code = 1
    except Exception as exc:  # noqa: BLE001
        record["status"] = "FAILED"
        record["error"] = str(exc)[:500]
        code = 1
    return _finish(settings, record, code)


def _finish(settings: Settings, record: dict[str, Any], code: int) -> tuple[int, dict[str, Any]]:
    record["finished_at"] = datetime.now(UTC).isoformat()
    log_dir = Path(settings.shadow_path).parent / "shadow_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"daily-{record['operation_id']}.json"
    if path.exists():
        raise FileExistsError(path.name)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)
    shadow_file = Path(settings.shadow_path)
    if shadow_file.exists():
        ShadowStore(shadow_file, namespace="forward").save_daily_operation(
            str(record["operation_id"]), record
        )
    return code, record
