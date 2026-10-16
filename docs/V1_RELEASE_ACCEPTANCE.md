# NomadQuant v1.0 acceptance

Version: `1.0.0`. Scope is frozen: a local research and supervised shadow workstation. An autonomous brokerage bot is not this release.

| Feature | Status | Evidence |
| --- | --- | --- |
| Windows install script | COMPLETE_WITH_LIMITATIONS | `scripts/install-local.ps1` checks Python 3.12, uv, Node, disk, `npm ci`, and the frontend build. It does not overwrite `.env`, reset SQLite, install scheduled tasks, download models, or apply shadow fills. A full rerun was not forced while the API held the virtualenv. |
| Start and stop | COMPLETE | `start-nomadquant.ps1` binds 127.0.0.1, waits for health, and records PIDs. `stop-nomadquant.ps1` stops only that tree. |
| Doctor and verify-all | COMPLETE | `doctor.ps1` reports disconnected Ollama or Alpaca as warnings. `verify-all.ps1` is the release gate. |
| Command Center | COMPLETE_WITH_LIMITATIONS | Live API, broker, Ollama, coverage, shadow equity, last worker, and next-step links. Broker balances appear only when the paper account can be read. |
| Market Explorer | COMPLETE_WITH_LIMITATIONS | Stored SIP daily candles, volume, ranges, and delayed-history labels. Not a live quote. |
| Research Lab | COMPLETE_WITH_LIMITATIONS | Experiment runs, equity, drawdown, trades, decisions, and verifier states. Run `?run=` selects a stable id. Split and dividend files are absent, so audits can stay `NOT_EVALUABLE`. |
| Agents | COMPLETE_WITH_LIMITATIONS | Local Ollama only. Retrospective memos. Failed numerical claims stay failed. No model is downloaded by the app. |
| Risk Policy Lab | COMPLETE | Deterministic rules on the internal $100 book. No order controls. |
| Shadow operations | COMPLETE_WITH_LIMITATIONS | Reconciled $100 ledger, prospective dry-runs, verification sample, and worker status. The forward pilot is not started. |
| Backup and restore | COMPLETE | SQLite online backup API, checksum manifest, confirm token, safety copy, and a test that a bad token or corrupt file leaves the current database intact. |
| Schema migration | COMPLETE_WITH_LIMITATIONS | Version stamp `1` is added without deleting rows. There is no multi-generation migration history before v1. |
| Broker order entry | NOT_IMPLEMENTED | No submit or cancel route. `ALLOW_ORDER_SUBMISSION=false`. |
| Autonomous trading | NOT_IMPLEMENTED | Out of scope. |
| Verified profitability | NOT_IMPLEMENTED | Not claimed. |

Hard gates that block a tag: a failed `verify-all.ps1`, a backup round trip that damages the sample database, an order route, or a red GitHub Actions run on the release commit.
