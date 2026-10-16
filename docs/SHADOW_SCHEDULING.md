# Shadow daily scheduling (opt-in)

Windows Task Scheduler support is **opt-in**. Nothing is installed automatically.

## Commands

```powershell
# Install weekday 5:45 PM local task (dry-run + reconcile only)
.\scripts\shadow-schedule.ps1 -Action install

# Status
.\scripts\shadow-schedule.ps1 -Action status

# Disable / remove
.\scripts\shadow-schedule.ps1 -Action disable

# Manual once
.\scripts\shadow-schedule.ps1 -Action run-once
```

## Guarantees

- Never submits broker orders.
- Does not launch Ollama.
- Uses a lock file to avoid overlapping runs.
- Logs under `data/shadow_logs/`.
- Preflight/cycle enforce NYSE calendar, holidays, and data availability in Python.

Adjust the trigger time so it maps to after US cash equity close / bar availability in America/New_York (respect DST on the host clock).
