# Roadmap

Phase 1 is a foundation. It is not a trading system. The $100 virtual capital is a constraint on later designs, not a profit target.

## Risk principles for later execution

When an execution path exists, it should default to:

- Cash-account assumptions
- Long-only US stocks and ETFs
- Fractional shares where the broker supports them
- No leverage
- No short selling
- No options
- No autonomous live trading
- Low turnover
- Explicit limits on position size, gross exposure, order size, and loss
- Fail closed when data is missing or stale
- An independent risk approval before every order
- Persistent idempotency keys and broker reconciliation
- An emergency stop and a cancel control

None of those execution controls are implemented yet, because there is no order path to attach them to. The principle that is implemented now is refusal: live mode, live URLs, and order submission cannot be turned on.

An LLM must not be able to skip the risk check or call broker order tools. The system must be able to decide not to trade. An empty target list is a successful strategy output.

## Phase 1 — foundation (this repository)

- Paper-only configuration and secret handling
- Read-only Alpaca account and positions
- Local status dashboard
- Research, security, and license documents
- Typed protocols with no fake implementations

## Phase 2 — point-in-time market data

Build a local daily-bar store for a small US ETF universe. Every bar needs an `as_of` timestamp. `MarketDataProvider.get_bars` must refuse bars that were not knowable at the cutoff. Tests should try to read the future and fail. Still no orders and no strategy claim.

Free data has holes, revision lag, and weak corporate-action history. The store has to record the vendor and the retrieval time instead of pretending the file is a clean institutional feed.

## Phase 3 — one reproducible backtest

Implement `BacktestEngine` for a single pre-registered hypothesis, with costs, chronological splits, and the three benchmarks in the research standards (buy-and-hold SPY, cash, and a simple baseline). Record every trial. Label the output as a backtest.

## Phase 4 — risk engine before any paper order

Implement `RiskEngine` against the $100 constraint and the limits above. Only after it can reject orders should a paper order gateway exist. The gateway is not given to an agent. Reconciliation and idempotency keys land in SQLite before the first paper submit.

## Phase 5 — research agents, still without a broker tool

Add an agent runner behind the provider abstraction (local Ollama or an OpenAI-compatible gateway). Tools are limited to reading local data, writing notes, and requesting a backtest. The dashboard can show those notes. It still has no button that trades.

## Explicitly out of scope until a separate decision

- Live trading
- Options, shorts, and leverage
- Copying Lean, NautilusTrader, or vectorbt into this repository
- Any statement that a backtest is realized profit
