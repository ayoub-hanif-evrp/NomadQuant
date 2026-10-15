# Offline quality gate for NomadQuant. Does not place orders.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "== ruff =="
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .

Write-Host "== mypy =="
uv run --no-sync mypy src

Write-Host "== pytest =="
uv run --no-sync pytest -q

Write-Host "== frontend =="
Set-Location apps\web
npm run lint
npx tsc --noEmit
npm run build
Set-Location ..\..

Write-Host "== route safety =="
uv run --no-sync python -c @"
from fastapi.testclient import TestClient
from nomadquant.api.app import create_app
from tests.conftest import make_settings
from pathlib import Path
import tempfile
with tempfile.TemporaryDirectory() as tmp:
    app = create_app(make_settings(Path(tmp)))
    with TestClient(app) as client:
        paths = client.app.openapi()['paths']
    for path, ops in paths.items():
        assert 'order' not in path.lower()
        assert set(ops).intersection({'get','post','put','patch','delete'}) == {'get'}
    print('PASS no order routes; GET-only API')
"@

Write-Host "ALL CHECKS PASSED"
