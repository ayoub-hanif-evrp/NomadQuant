"""SQLite-aware local backup and restore. Credentials are never included."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nomadquant.config import Settings
from nomadquant.ops import SCHEMA_VERSION


class BackupError(RuntimeError):
    """A backup or restore stopped before changing the live files."""


def artifact_map(settings: Settings) -> dict[str, Path]:
    root = Path(settings.database_path).parent
    return {
        "audit_events": Path(settings.database_path),
        "market_data": Path(settings.market_data_path),
        "research": Path(settings.research_path),
        "agents": Path(settings.agents_path),
        "agent_benchmarks": Path(settings.agent_benchmark_path),
        "risk": Path(settings.risk_path),
        "shadow": Path(settings.shadow_path),
        "agent_memos": Path(settings.agent_memo_root),
        "configuration_metadata": root / "schema-catalog.json",
    }


def backup_local(settings: Settings, destination: Path) -> dict[str, Any]:
    """Write a consistent backup. Existing live databases are not modified."""
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    included: list[dict[str, Any]] = []
    for name, source in artifact_map(settings).items():
        if name == "configuration_metadata":
            continue
        if not source.exists():
            included.append({"name": name, "status": "ABSENT", "path": str(source)})
            continue
        if source.is_dir():
            included.append(_copy_tree(name, source, destination / source.name))
        else:
            included.append(_backup_sqlite(name, source, destination / source.name))
    code = _code_version()
    body = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "code_version": code,
        "credentials_included": False,
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
        path = source / str(item["archive_name"])
        if not path.exists():
            problems.append(f"missing:{item['name']}")
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
    restored: list[str] = []
    try:
        for item in manifest["artifacts"]:
            if item.get("status") != "PRESENT":
                continue
            archive = source / str(item["archive_name"])
            target = Path(str(item["original_path"]))
            if target.exists():
                _preserve(target, safety / target.name)
            _install(archive, target)
            restored.append(item["name"])
    except Exception as exc:
        raise BackupError(
            f"Restore stopped. Current files that were copied first are in {safety}."
        ) from exc
    return {
        "status": "RESTORED",
        "restored": restored,
        "safety_copy": str(safety),
        "rollback": (
            "Stop NomadQuant, then copy the safety-copy files back over the live data "
            "directory. Do not delete the safety copy until the next backup verifies."
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


def _present(name: str, source: Path, archive_name: str, digest: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": "PRESENT",
        "original_path": str(source),
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
    source_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dest_conn = sqlite3.connect(safety)
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        source_conn.close()


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


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
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
