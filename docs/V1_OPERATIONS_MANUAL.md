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
uv run nomadquant-shadow worker --mode shadow-apply
```

Run these only after you decide to change the forward ledger. `confirm` stores a one-time internal approval when the state is `READY_TO_START` and the preview hash still matches. It expires in 30 minutes, binds the ledger version, policy hash, feed, and market fingerprint, and is consumed by one `shadow-apply`. It does not place a broker order and does not enable later scheduled applies. Blocked, waiting, and failed states cannot be approved. Today the workstation is `WAITING_FOR_SESSION`, so confirm will reject.

A later unattended schedule is separate. It requires the exact phrase and an expiry within 31 days, and it is not enabled by installation or by `confirm`. The daily steps are in `docs/FORWARD_PILOT_RUNBOOK.md`.

```powershell
uv run nomadquant-shadow pilot enable-schedule --confirm ENABLE_INTERNAL_SHADOW_SCHEDULE --until 2026-11-16T18:00:00+00:00
uv run nomadquant-shadow pilot disable-schedule --confirm DISABLE_INTERNAL_SHADOW_SCHEDULE
```

## Backup and restore

```powershell
.\scripts\backup-local.ps1
```

Read `confirm_token` from the new `manifest.json`. Stop the app, then:

```powershell
.\scripts\restore-local.ps1 -Source data\backups\<stamp> -Confirm <token>
```

Stop the app first so writers are quiesced. Each SQLite file is backed up with the online backup API. That is not one atomic snapshot across every database. A safety copy is written to `data\restore-safety`. If restore stops, the safety copy is copied back automatically; if that fails, copy it back yourself. A wrong token, a bad checksum, a corrupt database, or a path outside the allowlist does not replace live files. The confirm token is a checksum, not a signature. Backups are not uploaded. `.env` is not included.

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
| Home | What is happening, what needs attention, and the next step. |
| Decisions | The decision story: market, signal, agents, risk, recommendation, approval. |
| Agents | How Researcher, Skeptic, Reviewer, and the deterministic risk gate relate. |
| Portfolio | The internal $100 shadow book. |
| Market | Stored SPY and QQQ coverage in plain English. |
| Approvals | One-time internal shadow permissions. Not broker orders. |
| Advanced | The previous workbench: research, runs, risk, shadow operations, and health. |

## Approval email

An approval request is stored in `data/approvals.sqlite`. The email, or the local file under `data/approval-outbox` when `SMTP_HOST` or `APPROVAL_EMAIL_TO` is blank, contains a review link. Opening the link does not use the token. Confirming on that page does. The token is one-time, expires, and is stored only as a hash. Approval records permission for an internal shadow step. It does not apply the live ledger by itself, does not bypass risk checks, and does not submit an Alpaca order.

Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and `APPROVAL_EMAIL_TO` only in `.env`. Do not put those values in the frontend.
