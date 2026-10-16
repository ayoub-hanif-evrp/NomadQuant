# NomadQuant

NomadQuant 1.0.1 is a locally hosted, paper-only research and supervised shadow workstation. It provides configuration locks, a read-only Alpaca paper adapter, a local daily-bar store, an offline Quant Research Lab with verification, and a monitoring dashboard.

It does not place orders. Offline backtests are labeled as simulated research, not broker trading. Nothing in this repository is evidence of profit.

## Operating limits

- Trading mode is locked to `paper`.
- Order submission is locked off. There is no order endpoint.
- The Alpaca base URL is locked to `https://paper-api.alpaca.markets`.
- Internal strategy capital is locked at **$100**. That number is not the Alpaca paper account balance.
- The API binds to `127.0.0.1` only.
- Credentials are read from the environment on the backend. They are not sent to the browser.

Alpaca paper accounts are usually seeded with about $100,000 of simulated equity. Alpaca does not provide a reliable public setting to resize that balance to $100. NomadQuant therefore keeps an internal $100 virtual allocation and shows broker equity separately. The $100 figure is a constraint on later research, not a target return.

## Requirements

- Windows, Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js 22 or newer
- Optional: an Alpaca **paper** API key and secret

## Configure

From the repository root:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and set `ALPACA_API_KEY` and `ALPACA_API_SECRET` from the Alpaca dashboard's paper-trading API keys. Leave both blank to run in disconnected mode. Do not put live keys in this file. Do not commit `.env`.

## Install, start, stop

From the repository root in PowerShell:

```powershell
.\scripts\install-local.ps1
.\scripts\start-nomadquant.ps1
```

Open `http://127.0.0.1:3000`. Stop only the processes that script started:

```powershell
.\scripts\stop-nomadquant.ps1
.\scripts\doctor.ps1
.\scripts\verify-all.ps1
```

Backups stay on this PC. They do not include `.env`.

```powershell
.\scripts\backup-local.ps1
.\scripts\restore-local.ps1 -Source data\backups\STAMP -Confirm CONFIRM_TOKEN
```

The app starts with blank Alpaca keys and with Ollama stopped. Those states are disconnected, not crashes. Installation does not download models, register Task Scheduler jobs, or apply a shadow fill.

## Start

Use two PowerShell windows. Both commands assume the repository root is the current directory.

Backend:

```powershell
uv sync --all-groups
uv run nomadquant-api
```

The API listens on `http://127.0.0.1:8000`. Interactive docs are at `http://127.0.0.1:8000/docs`.

Frontend:

```powershell
Set-Location apps\web
npm install
npm run dev
```

The dashboard listens on `http://127.0.0.1:3000` (Command Center, Market Explorer, Research Lab, Decision Intelligence, Agents, Risk Policy Lab, Activity, Runs).

Equivalent scripts: `.\scripts\dev-api.ps1` and `.\scripts\dev-web.ps1`.

## Run a research experiment

Requires a complete local market-data window for the symbols and feed in the experiment file. Results are offline **backtests**, not paper trades.

```powershell
uv run nomadquant-research run --experiment experiments/spy_tsmom_v1.json
uv run nomadquant-research replay --run-id 2
uv run nomadquant-research verify --run-id 2
```

Inspect the Research Lab at `http://127.0.0.1:3000/research` and Market Explorer charts at `http://127.0.0.1:3000/market-data` while the API is running.

## Verify the paper account

Create `.env` yourself from `.env.example`. Set `ALPACA_API_KEY` and `ALPACA_API_SECRET` to a paper key pair from the Alpaca dashboard. Leave `ALPACA_BASE_URL` at `https://paper-api.alpaca.markets`. Do not paste keys into a chat. Restart the API after saving the file.

With the API already running:

```powershell
.\scripts\verify-paper.ps1
```

The script calls the local read-only API, prints PASS or FAIL for each check, and does not place orders. Broker equity is reported separately from the internal $100 limit. A missing `.env` is a configuration gap, not an authentication or network failure.

## Download daily bars

This does not run at install or at API startup. It writes `data/market.sqlite`, which is gitignored. The default feed is consolidated SIP. Raw bars are not dividend-adjusted total returns.

```powershell
uv run nomadquant-data sync --symbols SPY,QQQ --start 2018-01-01 --feed sip
uv run nomadquant-data report
```

If the account is not entitled to SIP, the command exits with an instruction to rerun the same arguments with `--feed iex`. IEX is a single-exchange feed and is stored separately. The assumptions and limits are in [docs/MARKET_DATA.md](docs/MARKET_DATA.md).

## Checks

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
Set-Location apps\web
npm run lint
npx tsc --noEmit
```

Pytest warns that Starlette wants `httpx2` and that `websockets.legacy` is deprecated. Neither warning fails the suite.

## What is included

- Paper-only settings that reject live mode, live Alpaca URLs, non-local binds, and order submission
- Startup without Alpaca credentials, in disconnected mode
- Read-only account and position retrieval, with rate limits and connection errors returned as data
- `GET /health`, broker status, `GET /api/market-data/status`, `GET /api/market-data/bars`, observability, and research verify/replay routes (all GET-only)
- SQLite operational, market, and research databases under `data/` (gitignored)
- Raw daily SPY/QQQ bars in `data/market.sqlite`, with a 16:30 New York availability model
- One pre-registered SPY time-series momentum backtest with independent replay and verification
- Structured logs that redact configured secrets
- A premium dark research terminal: interactive SIP daily charts, date-aligned equity/drawdown charts, decision drill-down, activity search/histogram
- Local Ollama research agents (Researcher → Skeptic → Reviewer), claim checker, agent SQLite history, and benchmark CLI
- Deterministic Risk Policy Lab against the internal $100 ledger (proposal-only; no order submission)

## What is not included

- Order placement, cancellation, or liquidation
- Live trading
- Dividend-adjusted total-return series, Qlib, or DuckDB
- Autonomous execution or start/pause/stop trading controls
- Claims of statistical significance or profitability from backtests
- Paid / remote LLM providers

## Layout

```text
apps/api/          ASGI entrypoint
apps/web/          Next.js dashboard
src/nomadquant/    Python package
tests/             Pytest suite
docs/              Architecture, research standards, security, licenses
scripts/           PowerShell dev launchers
data/              Local SQLite files (gitignored)
```

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/MARKET_DATA.md](docs/MARKET_DATA.md)
- [docs/DATA_QUALITY.md](docs/DATA_QUALITY.md)
- [docs/RESEARCH_STANDARDS.md](docs/RESEARCH_STANDARDS.md)
- [docs/SECURITY.md](docs/SECURITY.md)
- [docs/DEPENDENCY_REVIEW.md](docs/DEPENDENCY_REVIEW.md)
- [docs/ROADMAP.md](docs/ROADMAP.md)
- [docs/DECISIONS/0001-initial-architecture.md](docs/DECISIONS/0001-initial-architecture.md)
- [docs/DECISIONS/0002-proprietary-license.md](docs/DECISIONS/0002-proprietary-license.md)

## Local AI research review

Requires Ollama on `127.0.0.1:11434` and an installed model (recommended daily: `qwen3.5:9b` after local benchmarks).

```powershell
uv run --no-sync python -c "from nomadquant.agents.cli import main; main(['status'])"
uv run --no-sync python -c "from nomadquant.agents.cli import main; main(['run','--research-run-id','2','--model','qwen3.5:9b'])"
uv run --no-sync python -c "from nomadquant.agents.cli import main; main(['benchmark','--models','qwen3.5:9b,gemma4:12b','--research-run-id','2'])"
```

After `uv sync` (stop the API first if Windows locks the scripts), the same commands work as `uv run nomadquant-agent ...`. Inspect results at `http://127.0.0.1:3000/agents`. Reviews are retrospective and never place orders.

## Supervised daily workflow

One workflow. Installation and tests do not apply shadow fills.

| Step | Command | What it may change |
| --- | --- | --- |
| Inspect | `uv run nomadquant-shadow daily --mode inspect` | No download, no cash or holdings change, no broker order. Writes a daily log. |
| Sync + inspect | `uv run nomadquant-shadow daily --mode inspect --sync` | Read-only historical bars into the local market database. No shadow fill. |
| Dry-run | `uv run nomadquant-shadow daily --mode dry-run` | Signal and risk preview. No cash, holdings, or reservation change. |
| Supervised shadow-apply | Preview first, then `uv run nomadquant-shadow worker --mode shadow-apply` | Internal ledger only, after you accept the preview hash. No broker order. |

```powershell
uv run nomadquant-shadow pilot preview
uv run nomadquant-shadow pilot confirm --approval PREVIEW_HASH
uv run nomadquant-shadow worker --mode shadow-apply
```

`confirm` stores a one-time internal-shadow approval only when the pilot state is `READY_TO_START`. It does not apply a fill, does not enable later scheduled applies, and is not an Alpaca order. `worker --mode shadow-apply` consumes that approval. A committed simulated fill has no automatic undo. `recover` only releases an interrupted reservation. Do not run shadow-apply until you intend to change the forward ledger.

Dashboard: `http://127.0.0.1:3000/shadow`. Uses the internal $100 ledger only. No Alpaca orders.

## Risk Policy Lab (hypothetical only)

```powershell
uv run --no-sync python -c "from nomadquant.risk.cli import main; main(['status'])"
uv run --no-sync python -c "from nomadquant.risk.cli import main; main(['evaluate','--proposal-id','demo-1','--symbol','SPY','--side','buy','--qty','0.01','--price','500'])"
```

Dashboard: `http://127.0.0.1:3000/strategies`. Verdicts never submit broker orders.

## Suggested next milestone

v1.0 is the local research and supervised shadow product. Read [docs/V1_OPERATIONS_MANUAL.md](docs/V1_OPERATIONS_MANUAL.md) and [docs/V1_LIMITATIONS.md](docs/V1_LIMITATIONS.md). An Alpaca paper-order gateway is not part of this release.

## License

NomadQuant is proprietary. All rights are reserved. See [LICENSE](LICENSE). Third-party packages keep their own licenses, reviewed in `docs/DEPENDENCY_REVIEW.md`. Those licenses do not give anyone rights in the NomadQuant code.
