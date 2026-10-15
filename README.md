# NomadQuant

NomadQuant is a locally hosted, paper-only foundation for algorithmic trading research. Phase 1 provides configuration locks, a read-only Alpaca paper adapter, a small operational database, and a local status dashboard.

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

On 15 October 2026 those commands passed in this workspace: Ruff reported no issues, mypy reported no issues, pytest reported 27 passed, and the dashboard lint and typecheck completed without errors. Pytest warns that Starlette wants `httpx2` and that `websockets.legacy` is deprecated. Neither warning failed the suite.

## What Phase 1 includes

- Paper-only settings that reject live mode, live Alpaca URLs, non-local binds, and order submission
- Startup without Alpaca credentials, in disconnected mode
- Read-only account and position retrieval, with rate limits and connection errors returned as data
- `GET /health`, `GET /api/system/status`, `GET /api/broker/account`, `GET /api/broker/positions`
- SQLite startup log in `data/nomadquant.db`
- Structured logs that redact configured secrets
- Typed extension protocols for later data, research, strategy, backtest, risk, and paper-broker work
- A dark local dashboard with honest "Not implemented yet" pages

## What Phase 1 does not include

- Order placement, cancellation, or liquidation
- Live trading
- A strategy, backtest, equity curve, or performance number
- Market-data storage, Qlib, DuckDB, Ollama, or an agent runtime
- Start, pause, or stop controls for trading

## Layout

```text
apps/api/          ASGI entrypoint
apps/web/          Next.js dashboard
src/nomadquant/    Python package
tests/             Pytest suite
docs/              Architecture, research standards, security, licenses
scripts/           PowerShell dev launchers
data/              Local SQLite database (gitignored)
```

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/RESEARCH_STANDARDS.md](docs/RESEARCH_STANDARDS.md)
- [docs/SECURITY.md](docs/SECURITY.md)
- [docs/DEPENDENCY_REVIEW.md](docs/DEPENDENCY_REVIEW.md)
- [docs/ROADMAP.md](docs/ROADMAP.md)
- [docs/DECISIONS/0001-initial-architecture.md](docs/DECISIONS/0001-initial-architecture.md)

## Suggested Phase 2 prompt

Add a local point-in-time daily-bar store for a small long-only US ETF universe. Persist bars with an `as_of` timestamp, serve them through the `MarketDataProvider` protocol, and add tests that reject any bar not yet knowable at the requested cutoff. Do not submit orders, do not add a live broker, and do not claim a strategy result.

## License

NomadQuant is released under the MIT License. Third-party licenses are reviewed in `docs/DEPENDENCY_REVIEW.md`.
