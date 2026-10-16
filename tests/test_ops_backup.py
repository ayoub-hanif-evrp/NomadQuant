"""Backup, restore, and schema stamping stay off the live forward ledger."""

import json
import sqlite3
from pathlib import Path

import pytest

from nomadquant.config import Settings
from nomadquant.ops import backup as backup_module
from nomadquant.ops.backup import BackupError, backup_local, restore_local
from nomadquant.ops.migrate import stamp_schema
from nomadquant.shadow.store import LABEL_RETRO, shadow_path_for_label


def _settings(root: Path) -> Settings:
    data = root / "data"
    data.mkdir(parents=True)
    (data / "agent-memos").mkdir()
    (data / "agent-memos" / "note.txt").write_text("memo", encoding="utf-8")
    for name in (
        "nomadquant.db",
        "market.sqlite",
        "research.sqlite",
        "agents.sqlite",
        "agent-benchmarks.sqlite",
        "risk.sqlite",
        "shadow.sqlite",
    ):
        path = data / name
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, body TEXT)")
        connection.execute("INSERT INTO sample (body) VALUES ('kept')")
        connection.commit()
        connection.close()
    return Settings(
        database_path=str(data / "nomadquant.db"),
        market_data_path=str(data / "market.sqlite"),
        research_path=str(data / "research.sqlite"),
        agents_path=str(data / "agents.sqlite"),
        agent_memo_root=str(data / "agent-memos"),
        agent_benchmark_path=str(data / "agent-benchmarks.sqlite"),
        risk_path=str(data / "risk.sqlite"),
        shadow_path=str(data / "shadow.sqlite"),
    )


def test_backup_round_trip_and_bad_token(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    manifest = backup_local(settings, tmp_path / "backup-1")
    assert manifest["credentials_included"] is False
    assert manifest["verification"] == "PASS"
    shadow = Path(settings.shadow_path)
    connection = sqlite3.connect(shadow)
    connection.execute("UPDATE sample SET body = 'changed'")
    connection.commit()
    connection.close()
    with pytest.raises(BackupError):
        restore_local(settings, tmp_path / "backup-1", confirm="0" * 64)
    restored = restore_local(settings, tmp_path / "backup-1", confirm=manifest["confirm_token"])
    assert "shadow_forward" in restored["restored"]
    connection = sqlite3.connect(shadow)
    body = connection.execute("SELECT body FROM sample").fetchone()[0]
    connection.close()
    assert body == "kept"
    assert Path(restored["safety_copy"]).is_dir()


def test_corrupt_backup_is_refused(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    manifest = backup_local(settings, tmp_path / "backup-2")
    archive = tmp_path / "backup-2" / "shadow.sqlite"
    archive.write_bytes(b"not a database")
    with pytest.raises(BackupError):
        restore_local(settings, tmp_path / "backup-2", confirm=manifest["confirm_token"])
    connection = sqlite3.connect(settings.shadow_path)
    body = connection.execute("SELECT body FROM sample").fetchone()[0]
    connection.close()
    assert body == "kept"


def test_older_schema_keeps_rows(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE legacy_notes (id INTEGER PRIMARY KEY, body TEXT)")
    connection.execute("INSERT INTO legacy_notes (body) VALUES ('history')")
    connection.commit()
    connection.close()
    assert stamp_schema(path) == "1"
    connection = sqlite3.connect(path)
    body = connection.execute("SELECT body FROM legacy_notes").fetchone()[0]
    version = connection.execute(
        "SELECT value FROM nomadquant_meta WHERE key = 'schema_version'"
    ).fetchone()[0]
    connection.close()
    assert body == "history"
    assert version == "1"


def test_backup_includes_retrospective_logs_and_memos(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    retro = shadow_path_for_label(settings.shadow_path, LABEL_RETRO)
    connection = sqlite3.connect(retro)
    connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, body TEXT)")
    connection.execute("INSERT INTO sample (body) VALUES ('retro')")
    connection.commit()
    connection.close()
    logs = Path(settings.database_path).parent / "shadow_logs"
    logs.mkdir()
    (logs / "worker-1.json").write_text('{"run":"1"}', encoding="utf-8")
    secret = tmp_path / ".env"
    secret.write_text("ALPACA_API_SECRET=super-secret", encoding="utf-8")
    manifest = backup_local(settings, tmp_path / "full")
    names = {item["name"] for item in manifest["artifacts"] if item["status"] == "PRESENT"}
    assert {"shadow_retrospective", "worker_logs", "agent_memos", "configuration_metadata"} <= names
    assert manifest["confirm_token_is_signature"] is False
    assert manifest["atomic_whole_system_snapshot"] is False
    blob = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (tmp_path / "full").rglob("*")
        if path.is_file()
    )
    assert "super-secret" not in blob
    retro.unlink()
    (logs / "worker-1.json").unlink()
    restore_local(settings, tmp_path / "full", confirm=manifest["confirm_token"])
    connection = sqlite3.connect(retro)
    assert connection.execute("SELECT body FROM sample").fetchone()[0] == "retro"
    connection.close()
    assert (logs / "worker-1.json").read_text(encoding="utf-8") == '{"run":"1"}'
    memo = Path(settings.agent_memo_root) / "note.txt"
    assert memo.read_text(encoding="utf-8") == "memo"


def test_rejects_traversal_absolute_symlink_and_duplicate(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    backup_local(settings, tmp_path / "safe")
    manifest_path = tmp_path / "safe" / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["artifacts"][0]["archive_name"] = "../evil.sqlite"
    payload.pop("confirm_token", None)
    payload["confirm_token"] = backup_module._token(
        {key: value for key, value in payload.items() if key != "confirm_token"}
    )
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BackupError):
        restore_local(settings, tmp_path / "safe", confirm=payload["confirm_token"])
    payload["artifacts"][0]["archive_name"] = "C:/Windows/system.ini"
    payload.pop("confirm_token")
    payload["confirm_token"] = backup_module._token(
        {key: value for key, value in payload.items() if key != "confirm_token"}
    )
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BackupError):
        restore_local(settings, tmp_path / "safe", confirm=payload["confirm_token"])

    outside = tmp_path / "outside.sqlite"
    outside.write_text("nope", encoding="utf-8")
    link_dir = tmp_path / "linked"
    link_dir.mkdir()
    link = link_dir / "shadow.sqlite"
    try:
        link.symlink_to(outside)
    except OSError:
        link = None
    if link is not None and link.is_symlink():
        with pytest.raises(BackupError):
            backup_module._safe_archive(link_dir, "shadow.sqlite")

    payload = json.loads((tmp_path / "safe" / "manifest.json").read_text(encoding="utf-8"))
    present = [item for item in payload["artifacts"] if item["status"] == "PRESENT"]
    present[1]["archive_name"] = present[0]["archive_name"]
    payload["artifacts"] = present
    payload.pop("confirm_token", None)
    payload["confirm_token"] = backup_module._token(
        {key: value for key, value in payload.items() if key != "confirm_token"}
    )
    (tmp_path / "safe" / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BackupError):
        restore_local(settings, tmp_path / "safe", confirm=payload["confirm_token"])


def test_interrupted_restore_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path)
    manifest = backup_local(settings, tmp_path / "again")
    connection = sqlite3.connect(settings.shadow_path)
    connection.execute("UPDATE sample SET body = 'live'")
    connection.commit()
    connection.close()
    calls = {"n": 0}
    real = backup_module._install

    def fail_midway(archive: Path, target: Path) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("interrupted")
        real(archive, target)

    monkeypatch.setattr(backup_module, "_install", fail_midway)
    with pytest.raises(BackupError, match="safety copy"):
        restore_local(settings, tmp_path / "again", confirm=manifest["confirm_token"])
    connection = sqlite3.connect(settings.shadow_path)
    assert connection.execute("SELECT body FROM sample").fetchone()[0] == "live"
    connection.close()


def test_restore_uses_settings_paths_not_manifest_paths(tmp_path: Path) -> None:
    origin = _settings(tmp_path / "origin")
    backup_local(origin, tmp_path / "bundle")
    other = _settings(tmp_path / "other")
    decoy = tmp_path / "decoy.sqlite"
    payload = json.loads((tmp_path / "bundle" / "manifest.json").read_text(encoding="utf-8"))
    for item in payload["artifacts"]:
        item["original_path"] = str(decoy)
    payload.pop("confirm_token", None)
    payload["confirm_token"] = backup_module._token(
        {key: value for key, value in payload.items() if key != "confirm_token"}
    )
    (tmp_path / "bundle" / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    restore_local(other, tmp_path / "bundle", confirm=payload["confirm_token"])
    assert not decoy.exists()
    connection = sqlite3.connect(other.shadow_path)
    assert connection.execute("SELECT body FROM sample").fetchone()[0] == "kept"
    connection.close()


def test_wal_backup_includes_committed_rows(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    writer = sqlite3.connect(settings.market_data_path)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("INSERT INTO sample (body) VALUES ('visible')")
    writer.commit()
    manifest = backup_local(settings, tmp_path / "wal-backup")
    writer.close()
    connection = sqlite3.connect(tmp_path / "wal-backup" / "market.sqlite")
    rows = [row[0] for row in connection.execute("SELECT body FROM sample")]
    connection.close()
    assert "visible" in rows
    assert manifest["atomic_whole_system_snapshot"] is False
