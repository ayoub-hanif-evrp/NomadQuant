"""SQLite-aware local backup and restore. Credentials are never included."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nomadquant.config import Settings
from nomadquant.ops import SCHEMA_VERSION


class BackupError(RuntimeError):
    """A backup or restore stopped before changing the live files."""


ARCHIVE_NAMES = {
    "audit_events": "nomadquant.db",
    "market_data": "market.sqlite",
    "research": "research.sqlite",
    "agents": "agents.sqlite",
    "agent_benchmarks": "agent-benchmarks.sqlite",
    "risk": "risk.sqlite",
    "shadow_forward": "shadow.sqlite",
    "shadow_retrospective": "shadow_retrospective.sqlite",
    "agent_memos": "agent-memos",
    "worker_logs": "shadow_logs",
    "configuration_metadata": "schema-catalog.json",
}


def artifact_map(settings: Settings) -> dict[str, Path | None]:
    """Logical artifact id to a live path. None means the backup generates the file."""
    from nomadquant.shadow.store import LABEL_RETRO, shadow_path_for_label

    root = Path(settings.database_path).resolve().parent
    mapping: dict[str, Path | None] = {
        "audit_events": Path(settings.database_path),
        "market_data": Path(settings.market_data_path),
        "research": Path(settings.research_path),
        "agents": Path(settings.agents_path),
        "agent_benchmarks": Path(settings.agent_benchmark_path),
        "risk": Path(settings.risk_path),
        "shadow_forward": Path(settings.shadow_path),
        "shadow_retrospective": shadow_path_for_label(settings.shadow_path, LABEL_RETRO),
        "agent_memos": Path(settings.agent_memo_root),
        "worker_logs": root / "shadow_logs",
        "configuration_metadata": None,
    }
    seen: dict[str, str] = {}
    for name, path in mapping.items():
        if path is None:
            continue
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            raise BackupError(f"{name} and {seen[key]} resolve to the same path.")
        seen[key] = name
    return mapping


def backup_local(settings: Settings, destination: Path) -> dict[str, Any]:
    """Write a consistent backup. Existing live databases are not modified."""
    data_root = Path(settings.database_path).parent
    run_dir = data_root / "run"
    if _writers_alive(run_dir) or _worker_lock_active(data_root):
        raise BackupError(
            "Stop the application and the shadow worker before a consistency-sensitive backup."
        )
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    included: list[dict[str, Any]] = []
    for name, source in artifact_map(settings).items():
        archive_name = ARCHIVE_NAMES[name]
        if name == "configuration_metadata":
            catalog = destination / archive_name
            catalog.write_text(
                json.dumps(
                    {"schema_version": SCHEMA_VERSION, "artifacts": sorted(ARCHIVE_NAMES)},
                    indent=2,
                ),
                encoding="utf-8",
            )
            included.append(_present(name, None, archive_name, _sha256(catalog)))
            continue
        assert source is not None
        if source.is_symlink():
            raise BackupError(f"{name} is a symlink and was not backed up.")
        if not source.exists():
            included.append({"name": name, "status": "ABSENT", "archive_name": archive_name})
            continue
        target = destination / archive_name
        if source.is_dir():
            included.append(_copy_tree(name, source, target))
        else:
            included.append(_backup_sqlite(name, source, target))
            _integrity(target)
    run_dir = Path(settings.database_path).parent / "run"
    code = _code_version()
    body = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "code_version": code,
        "credentials_included": False,
        "confirm_token_is_signature": False,
        "atomic_whole_system_snapshot": False,
        "cross_database_consistency": "per_database_snapshot",
        "writers_quiesced": not _writers_alive(run_dir),
        "artifacts": included,
    }
    body["confirm_token"] = _token(body)
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    verification = verify_backup(destination)
    body["verification"] = verification["status"]
    manifest_path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    if verification["status"] != "PASS":
        raise BackupError("Backup checksum verification failed.")
    return body


def verify_backup(source: Path) -> dict[str, Any]:
    manifest = _read_manifest(source)
    problems: list[str] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        problems.append("schema_version")
    if manifest.get("credentials_included") is not False:
        problems.append("credentials")
    for item in manifest.get("artifacts") or []:
        if item.get("status") != "PRESENT":
            continue
        try:
            path = _safe_archive(source, str(item.get("archive_name")))
        except BackupError as exc:
            problems.append(str(exc))
            continue
        if not path.exists():
            problems.append(f"missing:{item['name']}")
            continue
        if path.suffix in {".sqlite", ".db"}:
            try:
                _integrity(path)
            except BackupError:
                problems.append(f"integrity:{item['name']}")
                continue
        digest = _sha256(path) if path.is_file() else _tree_sha256(path)
        if digest != item.get("sha256"):
            problems.append(f"checksum:{item['name']}")
    return {"status": "PASS" if not problems else "FAIL", "problems": problems}


def restore_local(
    settings: Settings,
    source: Path,
    *,
    confirm: str,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    """Replace live databases only after the confirm token matches."""
    source = source.resolve()
    manifest = _read_manifest(source)
    expected = str(manifest.get("confirm_token") or "")
    if confirm != expected or not expected:
        raise BackupError("Confirmation token does not match this backup.")
    check = verify_backup(source)
    if check["status"] != "PASS":
        raise BackupError("Backup failed verification and was not restored.")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise BackupError("Backup schema is not compatible with this release.")
    _require_stopped(run_dir or Path(settings.database_path).parent / "run")
    usage = shutil.disk_usage(Path(settings.database_path).parent)
    needed = sum(path.stat().st_size for path in source.rglob("*") if path.is_file())
    if usage.free < needed * 3:
        raise BackupError("Not enough free disk space for a safety copy and restore.")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safety = Path(settings.database_path).parent / "restore-safety" / stamp
    safety.mkdir(parents=True, exist_ok=False)
    names = [
        str(item.get("name")) for item in manifest["artifacts"] if item.get("status") == "PRESENT"
    ]
    if len(names) != len(set(names)):
        raise BackupError("Backup lists the same artifact more than once.")
    archives = [
        str(item.get("archive_name"))
        for item in manifest["artifacts"]
        if item.get("status") == "PRESENT"
    ]
    if len(archives) != len(set(archives)):
        raise BackupError("Backup lists two artifacts with the same archive name.")
    live = artifact_map(settings)
    restored: list[str] = []
    installed: list[tuple[str, Path]] = []
    current: tuple[str, Path] | None = None
    try:
        for item in manifest["artifacts"]:
            if item.get("status") != "PRESENT":
                continue
            name = str(item["name"])
            if name not in live:
                raise BackupError(f"Unknown artifact {name}.")
            archive = _safe_archive(source, str(item["archive_name"]))
            if ARCHIVE_NAMES[name] != archive.name:
                raise BackupError(f"Archive name for {name} is not allowlisted.")
            target = live[name]
            if target is None:
                target = Path(settings.database_path).resolve().parent / "schema-catalog.json"
            if target.exists() or target.is_symlink():
                _preserve(target, safety / ARCHIVE_NAMES[name])
            current = (name, target)
            _install(archive, target)
            installed.append((name, target))
            current = None
            restored.append(name)
    except Exception as exc:
        if current is not None:
            installed.append(current)
        _rollback(safety, installed)
        raise BackupError(
            "Restore stopped and the safety copy was copied back. "
            f"If that copy is incomplete, restore manually from {safety}."
        ) from exc
    return {
        "status": "RESTORED",
        "restored": restored,
        "safety_copy": str(safety),
        "atomic_whole_system_snapshot": False,
        "rollback": (
            "Stop NomadQuant. If the app does not match this backup, copy the safety "
            f"directory {safety} back onto the live data paths named in the manifest. "
            "The confirm token is a checksum, not a signature."
        ),
    }


def _backup_sqlite(name: str, source: Path, target: Path) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dest_conn = sqlite3.connect(target)
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        source_conn.close()
    return _present(name, source, target.name, _sha256(target))


def _copy_tree(name: str, source: Path, target: Path) -> dict[str, Any]:
    if target.exists():
        raise BackupError(f"Backup destination already has {target.name}.")
    shutil.copytree(source, target)
    return _present(name, source, target.name, _tree_sha256(target))


def _present(name: str, source: Path | None, archive_name: str, digest: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": "PRESENT",
        "archive_name": archive_name,
        "sha256": digest,
    }


def _install(archive: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".restore-tmp")
    if temporary.exists():
        if temporary.is_dir():
            shutil.rmtree(temporary)
        else:
            temporary.unlink()
    if archive.is_dir():
        shutil.copytree(archive, temporary)
        if target.exists():
            shutil.rmtree(target)
        temporary.replace(target)
        return
    if archive.suffix not in {".sqlite", ".db"}:
        shutil.copy2(archive, temporary)
        os.replace(temporary, target)
        return
    source_conn = sqlite3.connect(f"file:{archive}?mode=ro", uri=True)
    try:
        dest_conn = sqlite3.connect(temporary)
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        source_conn.close()
    os.replace(temporary, target)


def _preserve(source: Path, safety: Path) -> None:
    safety.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, safety)
        return
    if source.suffix not in {".sqlite", ".db"}:
        shutil.copy2(source, safety)
        return
    source_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dest_conn = sqlite3.connect(safety)
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        source_conn.close()


def _integrity(path: Path) -> None:
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"SQLite integrity check failed for {path.name}.") from exc
    if row is None or row[0] != "ok":
        raise BackupError(f"SQLite integrity check failed for {path.name}.")


def _safe_archive(source: Path, name: str) -> Path:
    if Path(name).name != name or name not in set(ARCHIVE_NAMES.values()):
        raise BackupError("Archive name is not an allowlisted file name.")
    root = source.resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise BackupError("Archive path escapes the backup directory.")
    if path.is_symlink():
        raise BackupError("Archive symlink is not allowed.")
    return path


def _rollback(safety: Path, installed: list[tuple[str, Path]]) -> None:
    for name, target in reversed(installed):
        saved = safety / ARCHIVE_NAMES[name]
        if not saved.exists():
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            continue
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        if saved.is_dir():
            shutil.copytree(saved, target)
        else:
            shutil.copy2(saved, target)


def _writers_alive(run_dir: Path) -> bool:
    pid_file = run_dir / "nomadquant.pids.json"
    if not pid_file.exists():
        return False
    try:
        payload = json.loads(pid_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return any(_pid_alive(int(pid)) for pid in payload.get("pids") or [])


def _require_stopped(run_dir: Path) -> None:
    pid_file = run_dir / "nomadquant.pids.json"
    if not pid_file.exists():
        return
    payload = json.loads(pid_file.read_text(encoding="utf-8"))
    alive = [int(pid) for pid in payload.get("pids") or [] if _pid_alive(int(pid))]
    if alive:
        raise BackupError(
            "NomadQuant is still running. Stop it with scripts\\stop-nomadquant.ps1 "
            "before restoring."
        )


def _worker_lock_active(data_root: Path) -> bool:
    """True when the shadow worker lock is younger than its stale window."""
    lock = data_root / "shadow_worker.lock"
    if not lock.is_file():
        return False
    age = datetime.now(UTC).timestamp() - lock.stat().st_mtime
    return age < 2 * 60 * 60


def _pid_alive(pid: int) -> bool:
    """True when the process exists. Does not signal it.

    On Windows, ``os.kill(pid, 0)`` is Ctrl+C, so this uses a query handle.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        kernel.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_manifest(source: Path) -> dict[str, Any]:
    path = source / "manifest.json"
    if not path.is_file():
        raise BackupError("Backup manifest is missing.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BackupError("Backup manifest is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise BackupError("Backup manifest is not an object.")
    return payload


def _token(body: dict[str, Any]) -> str:
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(str(item.relative_to(path)).encode("utf-8"))
        digest.update(_sha256(item).encode("utf-8"))
    return digest.hexdigest()


def _code_version() -> str:
    try:
        import nomadquant

        return str(nomadquant.__version__)
    except Exception:
        return "unknown"
