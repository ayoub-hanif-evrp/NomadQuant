# NomadQuant

NomadQuant is a locally hosted, paper-only foundation for algorithmic trading research. It provides configuration locks, a read-only Alpaca paper adapter, a small operational database, a local daily-bar store, and a local status dashboard.

It does not place orders, and it does not contain a trading strategy. Nothing in this repository is evidence of profit.

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

The dashboard listens on `http://127.0.0.1:3000`.

Equivalent scripts: `.\scripts\dev-api.ps1` and `.\scripts\dev-web.ps1`.

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
- `GET /health`, `GET /api/system/status`, `GET /api/broker/account`, `GET /api/broker/positions`, `GET /api/market-data/status`
- SQLite startup log in `data/nomadquant.db`
- Raw daily SPY/QQQ bars in `data/market.sqlite`, with a 16:30 New York availability model
- Structured logs that redact configured secrets
- Typed extension protocols for later data, research, strategy, backtest, risk, and paper-broker work
- A dark monitoring console for health, broker status, market data, activity, runs, and empty decision/agent states

## What is not included

- Order placement, cancellation, or liquidation
- Live trading
- A strategy, backtest, equity curve, or performance number
- Dividend-adjusted total-return series, Qlib, DuckDB, Ollama, or an agent runtime
- Start, pause, or stop controls for trading

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

## Suggested next milestone

One pre-registered backtest on the stored raw daily bars, with costs and the benchmarks in the research standards. Label it as a backtest. Do not adjust for dividends unless that adjustment is a separate, explicit series. Do not submit orders.

## License

NomadQuant is proprietary. All rights are reserved. See [LICENSE](LICENSE). Third-party packages keep their own licenses, reviewed in `docs/DEPENDENCY_REVIEW.md`. Those licenses do not give anyone rights in the NomadQuant code.
