# 0001 — Initial architecture

- Date: 2026-10-15
- Status: accepted
- License note: the MIT choice in this record is withdrawn. See [0002](0002-proprietary-license.md).

## Context

NomadQuant needs a local research foundation that can later paper-trade a $100 long-only book. The workstation has 16 GB of RAM. Live trading is out of scope. An LLM must not be able to bypass a risk check or submit an order. Several well-known trading repositories are large, and at least one popular backtest library is source-available rather than open source.

## Decision

Build a Python 3.12 modular monolith managed by uv, with FastAPI on `127.0.0.1` and a Next.js dashboard. Persist operational events in SQLite. Talk to Alpaca only through `alpaca-py`, only against `https://paper-api.alpaca.markets`, and only to read the account and positions.

Lock `TRADING_MODE=paper`, `ALLOW_ORDER_SUBMISSION=false`, and `INITIAL_VIRTUAL_CAPITAL_USD=100` in settings validation. Missing Alpaca keys start the process in a disconnected state instead of crashing.

Define `MarketDataProvider`, `ResearchAgent`, `Strategy`, `BacktestEngine`, `RiskEngine`, and a read-only `PaperBroker` protocol. Do not implement them beyond the read-only Alpaca adapter. Do not install Qlib, DuckDB, Lean, NautilusTrader, vectorbt, or an LLM runtime.

Reject vectorbt as a dependency because its Commons Clause means it is not OSI open source. Defer NautilusTrader because LGPL-3.0 duties and its weight are not justified yet. Do not adopt Lean as the runtime. NomadQuant's own license is decided in 0002, not by this record.

Treat Alpaca paper equity and the $100 virtual capital as different numbers. The broker account is often seeded near $100,000 and is not resized.

## Consequences

- The first milestone can be tested without a network and without a strategy story.
- Later order flow has to be a new component. It cannot be added by extending `PaperBroker` with a submit method, because that would erase the boundary the protocol is there to protect.
- Free data and a $100 ETF universe will not reproduce the cited papers. The research standards say that explicitly so a later backtest is not graded against those papers' headlines.
- Some capability arrives later than a demo would: there is no chart, no agent trace, and no trade button until the underlying record exists.
