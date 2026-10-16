# Shadow daily scheduling (opt-in)

Windows Task Scheduler support is **opt-in**. Nothing is installed automatically.

**Prompt 12:** the scheduled wrapper calls `nomadquant-shadow worker` (default **`inspect`** — preflight + reconcile only, no recover/fill). Use `-ShadowApply` on the scripts to opt into **`shadow-apply`** (simulated ledger + outbox delivery). That still **never** submits Alpaca or live orders.

## Commands

```powershell
# Install weekday task at local time equivalent to 17:45 America/New_York
.\scripts\shadow-schedule.ps1 -Action install

# Opt-in simulated apply (still no broker orders)
.\scripts\shadow-schedule.ps1 -Action install -ShadowApply

# Status (shows next 17:45 ET → local mapping)
.\scripts\shadow-schedule.ps1 -Action status

# Disable / remove
.\scripts\shadow-schedule.ps1 -Action disable

# Manual once (inspect default)
.\scripts\shadow-schedule.ps1 -Action run-once

# Manual dry-run cycle once
.\scripts\shadow-schedule.ps1 -Action run-once -DryRun

# Manual shadow-apply once
.\scripts\shadow-schedule.ps1 -Action run-once -ShadowApply
```

CLI equivalents:

```powershell
uv run nomadquant-shadow worker --mode inspect
uv run nomadquant-shadow worker --mode dry-run
uv run nomadquant-shadow worker --mode shadow-apply
uv run nomadquant-shadow recover   # explicit reservation recovery + outbox
```

## Guarantees

- Never submits broker orders.
- Does not launch Ollama or auto-sync market data.
- Worker lock file: `data/shadow_worker.lock` (stale locks cleared after 2h).
- Outcome JSON: `data/shadow_logs/worker-*.json`; text logs: `data/shadow_logs/shadow-*.log`.
- Exit codes: `0` ok/waiting/no_trade, `2` recovery_required (run `recover` before apply), `1` error.
- NYSE calendar / holidays enforced in Python preflight and cycle.
