# Shadow daily scheduling (opt-in)

Windows Task Scheduler support is **opt-in**. Nothing is installed automatically.

**Prompt 12:** the scheduled wrapper calls `nomadquant-shadow worker` (default **`inspect`** — preflight + reconcile only, no recover/fill). Use `-ShadowApply` on the scripts to opt into **`shadow-apply`** (simulated ledger + outbox delivery). That still **never** submits Alpaca or live orders.

## Commands

```powershell
# Opt-in install. Repeats every 30 minutes. shadow-daily.ps1 decides eligibility
# from America/New_York plus the NYSE calendar, so host DST does not freeze 17:45.
.\scripts\shadow-schedule.ps1 -Action install

# Opt-in simulated apply (still no broker orders)
.\scripts\shadow-schedule.ps1 -Action install -ShadowApply

# Status (next 17:45 America/New_York, shown in UTC as well)
.\scripts\shadow-schedule.ps1 -Action status

# Disable / remove
.\scripts\shadow-schedule.ps1 -Action disable

# Manual once (inspect default). This is not automatic trading.
.\scripts\shadow-schedule.ps1 -Action run-once

# Inspect plus an authorized historical SIP download. Still no simulated fill.
.\scripts\shadow-schedule.ps1 -Action install -Sync
.\scripts\shadow-schedule.ps1 -Action run-once -Sync

# Manual dry-run cycle once
.\scripts\shadow-schedule.ps1 -Action run-once -DryRun

# Manual shadow-apply once
.\scripts\shadow-schedule.ps1 -Action run-once -ShadowApply
```

CLI equivalents:

```powershell
uv run nomadquant-shadow data-check --feed sip
uv run nomadquant-shadow data-sync --feed sip   # explicit; not run by the scheduler
uv run nomadquant-shadow worker --mode inspect
uv run nomadquant-shadow worker --mode dry-run
uv run nomadquant-shadow worker --mode shadow-apply
uv run nomadquant-shadow daily --mode inspect
uv run nomadquant-shadow daily --mode dry-run
uv run nomadquant-shadow daily --mode inspect --sync   # explicit authenticated sync
uv run nomadquant-shadow daily --mode shadow-apply     # separate opt-in; still no broker orders
uv run nomadquant-shadow verify --cycle-id 1
uv run nomadquant-shadow recover   # explicit reservation recovery + outbox
```

## Guarantees

- Never submits broker orders.
- Does not launch Ollama or auto-sync market data.
- Worker lock file: `data/shadow_worker.lock` (stale locks cleared after 2h).
- Outcome JSON: `data/shadow_logs/worker-*.json`; text logs: `data/shadow_logs/shadow-*.log`.
- Exit codes: `0` ok/waiting/no_trade, `2` recovery_required (run `recover` before apply), `1` error.
- NYSE calendar / holidays enforced in Python preflight, cycle, and `ny_daily_gate`.
- A missed 17:45 stays due until that session is processed. Weekends and holidays catch up the previous session; they do not invent a new one.
- Authenticated `data-sync` stays off unless the task was installed with `-Sync`. That download is historical bars only. Inspect mode does not apply a simulated fill. `-ShadowApply` is a separate install and is not enabled by `-Sync`.
- The forward cycle uses a delayed hypothetical daily open. A 60-second bid/ask check belongs only to the observed-quote simulator.
