# NomadQuant v1.0 operations

This is the local research workstation. It does not submit broker orders.

## Install or update

```powershell
cd <repository>
.\scripts\install-local.ps1
```

The script checks Python 3.12, uv, and Node, installs the locked Python environment, runs `npm ci`, and builds the dashboard. If `.env` is missing it is copied from `.env.example`. An existing `.env` is not overwritten. SQLite files are not deleted.

Leave `ALPACA_API_KEY` and `ALPACA_API_SECRET` blank to run disconnected. Do not put live keys in `.env`.

## Start

```powershell
.\scripts\start-nomadquant.ps1
```

Open `http://127.0.0.1:3000`. The API is `http://127.0.0.1:8000`. If port 8000 or 3000 is already in use, the script stops and tells you. It will not start a second copy over a tracked process.

Ollama may be stopped. The Agents page then shows disconnected. That is expected.

## Daily inspection

```powershell
uv run nomadquant-shadow data-check --feed sip
uv run nomadquant-shadow preflight
uv run nomadquant-shadow reconcile
uv run nomadquant-shadow pilot status
uv run nomadquant-shadow daily --mode inspect
```

`daily --mode dry-run` previews a signal and does not change cash or holdings. `daily --mode inspect --sync` downloads historical bars only. Shadow-apply is a separate command and is not part of startup.

## Forward pilot

```powershell
uv run nomadquant-shadow pilot preview
uv run nomadquant-shadow pilot confirm --approval PREVIEW_HASH
```

Confirmation does not apply a fill. A later `uv run nomadquant-shadow worker --mode shadow-apply` changes the internal ledger only, and only after you intend that. v1 does not start the pilot for you.

## Backup and restore

```powershell
.\scripts\backup-local.ps1
```

Read `confirm_token` from the new `manifest.json`. Stop the app, then:

```powershell
.\scripts\restore-local.ps1 -Source data\backups\<stamp> -Confirm <token>
```

A safety copy is written to `data\restore-safety`. If restore stops, copy that safety directory back over `data` and do not delete it until the next backup verifies. A wrong token or a bad checksum does not replace live files. Backups are not uploaded. `.env` is not included.

## Verify and stop

```powershell
.\scripts\doctor.ps1
.\scripts\verify-all.ps1
.\scripts\stop-nomadquant.ps1
```

Stop affects only process IDs recorded by the start script. It does not stop every Python, Node, or Ollama process on the PC.

## What the pages are for

| Page | Use |
| --- | --- |
| Command Center | What is connected, covered, and waiting. |
| Market Explorer | Stored SPY and QQQ daily bars. |
| Research Lab | Backtests and verification. |
| Agents | Local retrospective memos. |
| Risk Policy Lab | Why a hypothetical order would be refused. |
| Shadow Operations | The internal $100 book and cycle evidence. |
| Activity | Audit events. |
