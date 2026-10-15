$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\apps\web")
npm run dev
