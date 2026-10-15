# Architecture

NomadQuant Phase 1 is a modular monolith. One Python process owns configuration, operational state, the read-only broker adapter, and the HTTP API. A separate Next.js process renders a localhost dashboard. They communicate only over `127.0.0.1`.

```text
apps/web  --GET-->  FastAPI  -->  Settings
                         |-->  SQLite system_events
                         |-->  SQLite market bars (read-only status)
                         |-->  AlpacaReadOnlyBroker
                                    |
                                    +--> https://paper-api.alpaca.markets

nomadquant-data sync --> Alpaca historical bars
                              |
                              +--> https://data.alpaca.markets
                              +--> data/market.sqlite
```

## Why a monolith

The machine has 16 GB of RAM and a single developer. Separate services for data, risk, execution, and agents would add process supervision and network failure modes before there is a strategy to run. Packages inside `src/nomadquant` are the extension points. A later component can move out of process if a measurement shows that it should.

## Package boundaries

| Module | Responsibility |
| --- | --- |
| `nomadquant.config` | Fail-closed settings. Paper mode, paper URL, disabled orders, $100 virtual capital, local bind. |
| `nomadquant.logging` | JSON logs. Configured secrets and assignment-style credentials are redacted. |
| `nomadquant.db` | SQLite file for operational events such as process startup. Not a research store. |
| `nomadquant.audit` | Structured events, runs, and future decision traces in that same operational file. |
| `nomadquant.broker` | Read-only Alpaca paper account and positions. |
| `nomadquant.marketdata` | Daily-bar download, validation, SQLite store, and cutoff reads. |
| `nomadquant.api` | Typed GET routes. |
| `nomadquant.contracts` | Protocols for data, research, strategy, backtest, risk, and paper-broker work. |

`apps/api/main.py` is a thin ASGI wrapper around `create_app()`. `apps/web` has no Alpaca credentials and no broker SDK.

## Broker versus strategy capital

`INITIAL_VIRTUAL_CAPITAL_USD` is an internal research constraint of $100. Alpaca paper equity is whatever balance the broker account currently has, often near $100,000 on a new paper account. The API returns both, with an explicit note that they are different. Phase 1 does not resize the Alpaca account and does not pretend the broker balance is $100.

## Request path

1. Settings load and reject live mode, live URLs, public binds, and order submission.
2. If either Alpaca key is missing, the process still starts. Broker routes return `disconnected`.
3. If both keys are present, `TradingClient` is constructed with `paper=True` and `url_override` set to the paper host.
4. Account and position reads share a five-second in-process cache so one dashboard refresh does not multiply calls.
5. HTTP 429 becomes `rate_limited`. Any other broker failure becomes `error`. The response message is fixed. Exception text is not returned, because broker errors can echo request material.
6. Logs record the exception class and status code, not the response body.

## Market data

`SqliteMarketDataProvider` implements `MarketDataProvider` for one feed. Reads compare the requested cutoff with modeled availability (16:30 America/New_York), not with the bar timestamp. The research database is `data/market.sqlite`. The API status route only reads it. Downloads happen through `nomadquant-data`, which calls `https://data.alpaca.markets` and does not use the trading client. Details are in [MARKET_DATA.md](MARKET_DATA.md) and [DATA_QUALITY.md](DATA_QUALITY.md).

## Contracts that are not implemented yet

`src/nomadquant/contracts.py` defines `ResearchAgent`, `Strategy`, `BacktestEngine`, `RiskEngine`, and `PaperBroker`. `MarketDataProvider` is implemented for raw daily bars.

`PaperBroker` has account and position reads only. Order methods are absent on purpose. A future order gateway must be a different object, callable only after `RiskEngine.evaluate` returns `approved=True`. A `ResearchAgent` must never receive that gateway or an Alpaca trading client.

`AlpacaReadOnlyBroker` follows that restriction. Its methods return status envelopes rather than the protocol's value objects, because a disconnected broker has to stay observable instead of raising through the API.

## What is deliberately missing

Live trading, order submission, a backtest engine, a risk implementation, and agents are out of scope. Daily bars exist so a later backtest has an inspectable input. They are not a performance result.

## Later extension points

- DuckDB or Parquet behind `MarketDataProvider` if the daily SQLite file stops being enough.
- Qlib behind a research job, not inside the request path of the API.
- An agent layer inspired by role separation, with tools limited to read-only research.
- Ollama or an OpenAI-compatible gateway behind a provider interface. No provider is installed now.
- A backtest engine that labels results as backtests.
- An order gateway that cannot be reached except through an approved `RiskDecision`.

Those pieces stay out of the Phase 1 dependency set. The license review is in [DEPENDENCY_REVIEW.md](DEPENDENCY_REVIEW.md). The sequence is in [ROADMAP.md](ROADMAP.md).
