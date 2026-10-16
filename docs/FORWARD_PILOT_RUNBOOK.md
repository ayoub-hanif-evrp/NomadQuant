# Forward pilot runbook

This is the daily procedure for the internal $100 shadow ledger. It does not submit Alpaca orders. Do not run a command that changes the forward ledger until you have decided to do that.

Historical research results and retrospective replay are not prospective performance.

## 1. Latest completed NYSE session

```powershell
uv run nomadquant-shadow data-check --feed sip
```

Read `eligible_end` and each symbol's `latest_stored`. The safe session is the last completed NYSE session whose daily bar is already stored. A session that is still open is not eligible.

## 2. Sync SPY and QQQ

This uses the local Alpaca data credentials for historical bars only.

```powershell
uv run nomadquant-shadow daily --mode inspect --sync --feed sip
```

Sync is off unless you pass `--sync`. Do not mix SIP and IEX in one ledger.

## 3. Dataset provenance

```powershell
uv run nomadquant-data report
uv run nomadquant-shadow data-check --feed sip
```

The report's `first_retrieved_at` is when this computer stored the row. A modeled 16:30 America/New_York availability time is not a verified point-in-time archive. Raw daily bars are not a dividend-adjusted total-return series.

An internal-shadow approval is bound to a content fingerprint of the SPY SIP observations in the strategy window. Changing one of those prices invalidates that approval even if the session count and the latest date stay the same.

## 4. Strategy eligibility

```powershell
uv run nomadquant-shadow pilot status
uv run nomadquant-shadow preflight
```

The strategy is `spy_tsmom_12_1` on SPY SIP. A rebalance is a month-start session, not every day. `signal_eligible` can be true while `rebalance_scheduled` is false. That is a waiting day, not a start.

## 5. The $100 ledger

```powershell
uv run nomadquant-shadow reconcile
```

Expect cash `100`, reserved cash `0`, empty holdings, and ledger version `1` until a supervised apply has changed it. Reconciliation must be ok before an apply. This balance is the internal shadow ledger, not the Alpaca paper account.

## 6. Approval preview

```powershell
uv run nomadquant-shadow pilot preview
```

Preview is read-only. Copy `preview_hash` only if you intend to confirm that exact preview. The hash covers the readiness state and the market-data fingerprint.

## 7. When a start is actually allowed

`pilot status` must say `READY_TO_START`.

That requires a scheduled rebalance, the observation the cycle needs, a reconciled ledger, and no block. `WAITING_FOR_SESSION`, `WAITING_FOR_DATA`, `BLOCKED`, `FAILED`, and `RECOVERY_REQUIRED` can be inspected. They cannot be approved.

Do not invent a month-start. If today is not a due rebalance, leave the pilot unstarted.

## 8. Confirm one internal-shadow operation

```powershell
uv run nomadquant-shadow pilot confirm --approval PREVIEW_HASH
```

This stores one approval for 30 minutes. It is bound to the preview hash, ledger version, strategy, risk-policy hash, feed `sip`, and the market fingerprint. It is consumed by one forward shadow-apply. It is not an Alpaca order, and it does not enable a schedule.

A second confirmation while one approval is still pending is rejected. A changed ledger, policy, feed, or relevant price makes the stored approval unusable.

## 9. Run one supervised cycle

Within 30 minutes of confirmation, and only when you mean to change the internal ledger:

```powershell
uv run nomadquant-shadow worker --mode shadow-apply
```

`daily --mode dry-run` does not change cash or holdings. `daily --mode shadow-apply` is the same class of write as the worker and also requires the approval.

The application guard still runs: reconciliation, preflight, and active reservations. A pending intent resumes only when it carries the grant from that consumed approval, or from a schedule you enabled yourself. An old intent without that grant does not get a fill.

## 10. Check the decision and the accounting

```powershell
uv run nomadquant-shadow reconcile
uv run nomadquant-shadow history --limit 20
uv run nomadquant-shadow verify --cycle-id CYCLE_ID
```

A no-trade cycle is not a fill. A missed month-start is an audit row, not a backfilled trade. Cash and holdings must still reconcile. The verifier exit code is 0 for PASS, 1 for FAIL, 2 for NOT_EVALUABLE, and 3 for INVALID_ARTIFACT.

## 11. Stop or disable a schedule

Scheduling is off unless you turn it on. Installation and `pilot confirm` do not enable it. A restart does not turn it back on after you disable it.

Enable only if you want later internal cycles without a new token, for at most 31 days:

```powershell
uv run nomadquant-shadow pilot enable-schedule --confirm ENABLE_INTERNAL_SHADOW_SCHEDULE --until 2026-11-16T18:00:00+00:00
```

Disable:

```powershell
uv run nomadquant-shadow pilot disable-schedule --confirm DISABLE_INTERNAL_SHADOW_SCHEDULE
```

Every scheduled cycle still has to pass the application guard. The schedule cannot authorize a broker order. After expiry, later cycles need a new one-time approval.

Stop the processes:

```powershell
.\scripts\stop-nomadquant.ps1
```

That stops only the process tree recorded by `start-nomadquant.ps1`.

## 12. After a crash

```powershell
uv run nomadquant-shadow reconcile
uv run nomadquant-shadow recover
```

`recover` releases an interrupted reservation and delivers the internal outbox. It does not undo a committed simulated fill and it does not submit a broker cancel. If a one-time approval was not consumed, it can still be used until it expires. If it was consumed in the same transaction as the cycle, a second apply does not create a second fill.

## 13. Backup and restore

Stop the API, the dashboard, and the shadow worker first. A backup is refused while those writers are still recorded as running. Each database is copied on its own. That is not one atomic snapshot of every database.

```powershell
.\scripts\stop-nomadquant.ps1
.\scripts\backup-local.ps1
```

The confirm token in `manifest.json` is a checksum, not a signature. `.env` is not in the backup.

```powershell
.\scripts\restore-local.ps1 -Source data\backups\<stamp> -Confirm <token>
```

Restore uses allowlisted artifact names. If a replacement fails, the safety copy under `data\restore-safety` is copied back. If that copy is incomplete, stop the app and copy the safety directory back onto the live data files yourself. Do not restore over a ledger you have not backed up.

## 14. Closed market, no rebalance, or missing data

- Market closed or no new session: `data-check` still shows the last stored session. Do not sync in a loop and do not apply.
- No month-start due: status stays `WAITING_FOR_SESSION` or preflight says no rebalance. Inspect or dry-run. Do not confirm.
- Missing bars: status is `WAITING_FOR_DATA`. Sync if you want the historical bars, then inspect again. Do not approve a blocked or waiting state.
- Ollama stopped: Agents shows disconnected. Shadow inspection does not need a model.
- Alpaca credentials absent: market sync stays disconnected. Stored bars can still be inspected.
