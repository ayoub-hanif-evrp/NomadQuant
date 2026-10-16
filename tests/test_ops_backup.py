"""Backup, restore, and schema stamping stay off the live forward ledger."""

import sqlite3
from pathlib import Path

import pytest

from nomadquant.config import Settings
from nomadquant.ops.backup import BackupError, backup_local, restore_local
from nomadquant.ops.migrate import stamp_schema


def _settings(root: Path) -> Settings:
    data = root / "data"
    data.mkdir()
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
    assert "shadow" in restored["restored"]
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
