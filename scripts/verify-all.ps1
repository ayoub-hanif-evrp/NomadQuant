# Offline quality gate for NomadQuant. Does not place orders.
# Native-command failures must stop the script ($ErrorActionPreference alone is insufficient).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [string]$Label = "command"
    )
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "FAILED: $Label (exit $LASTEXITCODE)"
    }
}

Write-Host "== ruff =="
Invoke-Native { uv run --no-sync ruff check . } "ruff check"
Invoke-Native { uv run --no-sync ruff format --check . } "ruff format"

Write-Host "== mypy =="
Invoke-Native { uv run --no-sync mypy src } "mypy"

Write-Host "== pytest =="
Invoke-Native { uv run --no-sync pytest -q } "pytest"

Write-Host "== frontend =="
Set-Location apps\web
Invoke-Native { npm run lint } "frontend lint"
Invoke-Native { npx tsc --noEmit } "tsc"
Invoke-Native { npm run build } "frontend build"
Set-Location ..\..

Write-Host "== route safety =="
Invoke-Native {
    uv run --no-sync python -c @"
from fastapi.testclient import TestClient
from nomadquant.api.app import create_app
from nomadquant.api.mutations import POST_ROUTES, assert_route_safety
from tests.conftest import make_settings
from pathlib import Path
import gc
import shutil
import tempfile
tmp = Path(tempfile.mkdtemp())
try:
    app = create_app(make_settings(tmp))
    with TestClient(app) as client:
        paths = client.app.openapi()['paths']
    assert_route_safety(paths)
    print('PASS no order routes; POST allowlist', sorted(POST_ROUTES))
finally:
    gc.collect()
    shutil.rmtree(tmp, ignore_errors=True)
"@
} "route safety"

Write-Host "== offline shadow e2e =="
Invoke-Native {
    uv run --no-sync pytest -q tests/test_shadow.py tests/test_shadow_reliability.py
} "shadow e2e"

Write-Host "ALL CHECKS PASSED"
