"""Daily shadow worker orchestration. Never submits broker orders."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from nomadquant.config import Settings
from nomadquant.shadow.cycle import LABEL_FORWARD, run_shadow_cycle
from nomadquant.shadow.gate import application_guard
from nomadquant.shadow.preflight import run_reconcile
from nomadquant.shadow.store import ShadowStore

WorkerMode = Literal["inspect", "dry-run", "shadow-apply"]
WorkerStatus = Literal[
    "HEALTHY",
    "WAITING_FOR_SESSION",
    "WAITING_FOR_DATA",
    "PENDING_OBSERVATION",
    "RISK_BLOCKED",
    "COMPLETED_NO_TRADE",
    "COMPLETED_FILL",
    "RECOVERY_REQUIRED",
    "FAILED",
]

_LOCK_NAME = "shadow_worker.lock"
_STALE_LOCK_HOURS = 2
_OUTCOME_PREFIX = "worker-"


def run_daily_worker(
    settings: Settings,
    *,
    mode: WorkerMode,
    data_dir: Path | str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Run the daily shadow pipeline under a data-dir lock.

    Exit codes: 0 ok/waiting/no_trade, 2 recovery_required, 1 error.
    """
    if mode not in {"inspect", "dry-run", "shadow-apply"}:
        raise ValueError(f"Unknown worker mode {mode!r}.")

    root = Path(data_dir or Path(settings.shadow_path).parent)
    log_dir = root / "shadow_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    lock_path = root / _LOCK_NAME
    started_at = datetime.now(UTC)
    run_id = uuid.uuid4().hex
    outcome: dict[str, Any] = {
        "run_id": run_id,
        "worker_status": "HEALTHY",
        "mode": mode,
        "started_at": started_at.isoformat(),
        "trading_state": "SHADOW_ONLY",
        "allow_order_submission": False,
        "notes": [
            "Market data sync is not automatic; import bars before apply cycles.",
            "Never submits Alpaca or broker orders.",
        ],
        "preflight": None,
        "reconcile": None,
        "cycle": None,
        "outbox": None,
        "recovery_inspect": None,
    }

    if not _acquire_lock(lock_path):
        outcome["worker_status"] = "FAILED"
        outcome["error"] = f"lock_held:{lock_path}"
        outcome["finished_at"] = datetime.now(UTC).isoformat()
        _write_outcome(log_dir, outcome)
        return 1, outcome

    exit_code = 1
    try:
        store = ShadowStore(settings.shadow_path, namespace="forward")
        before = store.snapshot()
        outcome["ledger_before"] = _ledger_view(before)
        active = store.list_active_reservations()
        pending = _pending_intents(store)
        recovery = {
            "active_reservations": len(active),
            "pending_intent_count": len(pending),
            "reservation_intent_ids": [r["intent_id"] for r in active],
        }
        outcome["recovery_inspect"] = recovery
        guard = application_guard(settings)
        outcome["preflight"] = guard["preflight"]
        outcome["reconcile"] = guard["reconcile"]
        outcome["gate"] = {
            "allowed": guard["allowed"],
            "reasons": guard["reasons"],
            "preflight_status": guard["preflight_status"],
            "reconcile_ok": guard["reconcile_ok"],
        }

        if active or "active_reservations" in guard["reasons"]:
            outcome["worker_status"] = "RECOVERY_REQUIRED"
            outcome["finished_at"] = datetime.now(UTC).isoformat()
            _write_outcome(log_dir, outcome)
            return 2, outcome

        preflight_status = str(guard.get("preflight_status") or "")
        if preflight_status == "BLOCKED":
            outcome["worker_status"] = "FAILED"
        elif preflight_status in {"WAITING_FOR_DATA", "NO_REBALANCE_DUE"}:
            outcome["worker_status"] = (
                "WAITING_FOR_DATA"
                if preflight_status == "WAITING_FOR_DATA"
                else "WAITING_FOR_SESSION"
            )
        elif preflight_status == "ALREADY_PROCESSED" and mode == "inspect":
            outcome["worker_status"] = "HEALTHY"

        if mode == "inspect":
            if outcome["worker_status"] == "HEALTHY" and not guard["reconcile_ok"]:
                outcome["worker_status"] = "FAILED"
            exit_code = _exit_for_status(outcome["worker_status"])
            outcome["finished_at"] = datetime.now(UTC).isoformat()
            _write_outcome(log_dir, outcome)
            return exit_code, outcome

        if not guard["allowed"]:
            if guard["reconcile"].get("recovery_required"):
                outcome["worker_status"] = "RECOVERY_REQUIRED"
            else:
                outcome["worker_status"] = "FAILED"
            outcome["cycle"] = None
            exit_code = _exit_for_status(outcome["worker_status"])
            outcome["finished_at"] = datetime.now(UTC).isoformat()
            _write_outcome(log_dir, outcome)
            return exit_code, outcome

        cycle_mode = "dry-run" if mode == "dry-run" else "apply"
        cycle_detail = run_shadow_cycle(
            market_path=settings.market_data_path,
            shadow_path=settings.shadow_path,
            risk_path=settings.risk_path,
            mode=cycle_mode,
            label=LABEL_FORWARD,
        )
        outcome["cycle"] = cycle_detail
        outcome["worker_status"] = _status_from_cycle(
            cycle_detail,
            preflight_status=preflight_status,
            pending_count=len(_pending_intents(store)),
        )

        after = store.snapshot()
        outcome["ledger_after"] = _ledger_view(after)
        outcome["pending_intents_resolved"] = len(pending) - len(_pending_intents(store))

        if mode == "shadow-apply":
            outcome["outbox"] = _deliver_outbox_safe(store, settings.risk_path)
            outcome["reconcile_after"] = run_reconcile(settings)
            after_ok = bool(outcome["reconcile_after"].get("ok"))
            if not after_ok:
                outcome["worker_status"] = "FAILED"
                outcome["error"] = "post_apply_reconcile_failed"
                outcome["gate"] = {**outcome["gate"], "post_apply": "blocked_pending_investigation"}

        if not outcome["reconcile"].get("ok") and outcome["worker_status"] == "HEALTHY":
            outcome["worker_status"] = "FAILED"

        exit_code = _exit_for_status(outcome["worker_status"])
        outcome["finished_at"] = datetime.now(UTC).isoformat()
        _write_outcome(log_dir, outcome)
        return exit_code, outcome
    except Exception as exc:  # noqa: BLE001
        outcome["worker_status"] = "FAILED"
        outcome["error"] = _sanitize(str(exc))
        outcome["finished_at"] = datetime.now(UTC).isoformat()
        _write_outcome(log_dir, outcome)
        return 1, outcome
    finally:
        _release_lock(lock_path)


def list_worker_runs(log_dir: Path | str, *, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    """Paginate durable worker outcomes. Corrupt files are reported, not overwritten."""
    directory = Path(log_dir)
    if not directory.is_dir():
        return {"items": [], "total": 0, "corrupt": [], "limit": limit, "offset": offset}
    files = sorted(directory.glob(f"{_OUTCOME_PREFIX}*.json"), key=lambda p: p.stat().st_mtime)
    items: list[dict[str, Any]] = []
    corrupt: list[str] = []
    for path in reversed(files):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            corrupt.append(path.name)
            continue
        if isinstance(payload, dict) and payload.get("run_id") and payload.get("finished_at"):
            items.append(payload)
        else:
            corrupt.append(path.name)
    page = items[offset : offset + limit]
    return {
        "items": page,
        "total": len(items),
        "corrupt": corrupt,
        "limit": limit,
        "offset": offset,
    }


def read_last_worker_run(log_dir: Path | str) -> dict[str, Any] | None:
    """Return the newest worker outcome JSON under ``shadow_logs``, if any."""
    directory = Path(log_dir)
    if not directory.is_dir():
        return None
    candidates = sorted(directory.glob(f"{_OUTCOME_PREFIX}*.json"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        return None
    try:
        payload = json.loads(candidates[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def outbox_backlog_count(store: ShadowStore) -> int | None:
    list_outbox = getattr(store, "list_outbox", None)
    if not callable(list_outbox):
        return None
    try:
        return len(list_outbox(undelivered_only=True, limit=1000))
    except Exception:  # noqa: BLE001
        return None


def recovery_required(store: ShadowStore) -> bool:
    return len(store.list_active_reservations()) > 0


def _pending_intents(store: ShadowStore) -> list[dict[str, Any]]:
    list_fn = getattr(store, "list_pending_intents", None)
    if callable(list_fn):
        rows = list_fn()
        return list(rows) if isinstance(rows, list) else []
    return store.pending_intents()


def _deliver_outbox_safe(store: ShadowStore, risk_path: str | Path) -> dict[str, Any] | None:
    try:
        from nomadquant.shadow.outbox import deliver_outbox
    except ImportError:
        return {"skipped": True, "reason": "outbox_module_unavailable"}
    if not callable(deliver_outbox):
        return {"skipped": True, "reason": "deliver_outbox_missing"}
    try:
        result = deliver_outbox(store, risk_path)
        return result if isinstance(result, dict) else {"delivered": 0}
    except Exception as exc:  # noqa: BLE001
        return {"delivered": 0, "errors": [str(exc)], "remaining": None}


def _status_from_cycle(
    detail: dict[str, Any],
    *,
    preflight_status: str,
    pending_count: int,
) -> WorkerStatus:
    cycle_status = str(detail.get("status", "")).lower()
    if cycle_status in {"error", "blocked"}:
        return "FAILED"
    if cycle_status in {"pending_data", "pending_observation"} or pending_count > 0:
        return "PENDING_OBSERVATION"
    if cycle_status == "filled":
        return "COMPLETED_FILL"
    if cycle_status in {"no_trade", "dry_run_approved", "hold"}:
        return "COMPLETED_NO_TRADE"
    if cycle_status == "risk_rejected":
        return "RISK_BLOCKED"
    if cycle_status == "insufficient_data" or preflight_status == "WAITING_FOR_DATA":
        return "WAITING_FOR_DATA"
    if preflight_status in {"NO_REBALANCE_DUE", "ALREADY_PROCESSED"}:
        return "WAITING_FOR_SESSION"
    return "HEALTHY"


def _exit_for_status(status: str) -> int:
    if status == "RECOVERY_REQUIRED":
        return 2
    if status == "FAILED":
        return 1
    return 0


def _acquire_lock(lock_path: Path) -> bool:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        age = datetime.now(UTC) - datetime.fromtimestamp(lock_path.stat().st_mtime, tz=UTC)
        if age < timedelta(hours=_STALE_LOCK_HOURS):
            return False
        lock_path.unlink(missing_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"{datetime.now(UTC).isoformat()}\n")
        return True
    except FileExistsError:
        return False


def _release_lock(lock_path: Path) -> None:
    lock_path.unlink(missing_ok=True)


def _ledger_view(snap: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": snap.get("version"),
        "cash_usd": str(snap.get("cash_usd")),
        "reserved_cash_usd": str(snap.get("reserved_cash_usd")),
        "holdings": {k: str(v) for k, v in dict(snap.get("holdings") or {}).items()},
    }


def _sanitize(text: str) -> str:
    redacted = re.sub(
        r"(?i)(api[_-]?key|secret|token|authorization|bearer)\s*[:=]\s*\S+",
        r"\1=[redacted]",
        text,
    )
    return redacted[:500]


def _write_outcome(log_dir: Path, outcome: dict[str, Any]) -> Path:
    run_id = str(outcome.get("run_id") or uuid.uuid4().hex)
    outcome["run_id"] = run_id
    path = log_dir / f"{_OUTCOME_PREFIX}{run_id}.json"
    if path.exists():
        raise FileExistsError(f"worker outcome already exists: {path.name}")
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(outcome, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)
    return path
