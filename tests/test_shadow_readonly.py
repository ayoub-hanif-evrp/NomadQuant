"""GET inspection does not create or migrate the shadow ledger."""

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from nomadquant.api.app import create_app
from nomadquant.shadow.store import MigrationRequired, ShadowStore
from tests.conftest import make_settings


def test_missing_ledger_is_not_created(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        first = client.get("/api/shadow/status")
        second = client.get("/api/shadow/status")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["initialized"] is False
    assert not Path(settings.shadow_path).exists()


def test_get_does_not_change_an_existing_ledger(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    store = ShadowStore(settings.shadow_path, namespace="forward")
    before = store.snapshot()
    digest = Path(settings.shadow_path).read_bytes()
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/shadow/status").status_code == 200
        assert client.get("/api/shadow/reconcile").status_code == 200
        assert client.get("/api/shadow/pilot").status_code == 200
    after = ShadowStore.open_readonly(settings.shadow_path)
    assert after is not None
    assert after.snapshot()["version"] == before["version"]
    assert after.snapshot()["cash_usd"] == before["cash_usd"]
    assert Path(settings.shadow_path).read_bytes()[:16] == digest[:16]


def test_old_schema_is_not_migrated(tmp_path: Path) -> None:
    path = tmp_path / "shadow.sqlite"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE legacy (id INTEGER)")
    connection.commit()
    connection.close()
    before = path.read_bytes()
    try:
        ShadowStore.open_readonly(path)
        raised = False
    except MigrationRequired:
        raised = True
    assert raised is True
    assert path.read_bytes() == before
