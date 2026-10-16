# NomadQuant v1.0 test report

Measurements below were taken on this Windows PC on 2026-10-16. They are single observations, not a percentile claim.

## Workstation doctor

`.\scripts\doctor.ps1` reported PASS for Python 3.12, uv, Node v24.21.0, `.env` present, web build present, about 215 GB free, market, research, shadow, risk, and agent databases present, API, dashboard, and local Ollama. No secret values were printed.

## Measured reads

| Call | Result |
| --- | --- |
| `GET /health` | 43 ms |
| `GET /api/shadow/pilot` | 546 ms |
| `GET /api/market-data/bars` SPY SIP 2026-01-01..2026-10-15 limit 300 | 55 ms |
| `GET /api/research/runs?limit=20` | 11 ms |
| `GET /api/observability/events?limit=50` | 15 ms |

Cold process startup was not remeasured while the API was already running. The start script waits on `/health` and `http://127.0.0.1:3000` and exits if either process dies immediately.

## Data and ledger

SIP SPY and QQQ each have 2209 sessions through 2026-10-15. The internal ledger is cash 100, reserved 0, version 1, reconcile ok, 0 fills. Pilot state `WAITING_FOR_SESSION`. `pilot_running` is false.

## Automated

- `tests/test_ops_backup.py`: backup round trip restores the prior row, a bad token does not restore, a corrupt archive is refused, and an older table keeps its row when schema version 1 is stamped.
- Isolated shadow BUY/HOLD/SELL, stale timestamps, verifier exit codes, and risk parity remain in the pytest suite run by `verify-all.ps1`.
- UI screenshots for the release candidate pages are in `docs/ui-shots/`. The Command Center shot is refreshed for the Ollama and equity lines.

## Security

| Check | Result |
| --- | --- |
| Trading mode | paper, startup rejects other values |
| Order routes | none; API is GET-only |
| Bind | 127.0.0.1 |
| CORS | local dashboard origins, GET only |
| Ollama | loopback only |
| Secrets in the browser | not sent |
| `.env` and SQLite in git | gitignored; backup excludes `.env` |
| Screenshots | no keys |
| Repository visibility | public; unchanged |

TradingView Lightweight Charts is attributed on the Market Explorer and is Apache-2.0. alpaca-py is Apache-2.0 and is used read-only. NomadQuant itself stays proprietary.

## Not run as a live mutation

Shadow-apply on the real forward ledger was not run. No Alpaca order was submitted. A full `install-local.ps1` was not repeated while the running API locked the virtualenv. The script is the supported setup path and `doctor.ps1` confirms the installed toolchain.
