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

## Phase 2 — daily market data

Local raw daily bars for SPY and QQQ, one feed at a time, with modeled availability at 16:30 America/New_York and a separate first-retrieved timestamp. Conflicting downloads are kept as revisions. This is not a verified point-in-time archive and not a dividend-adjusted total-return series. Still no orders and no strategy claim. See [MARKET_DATA.md](MARKET_DATA.md).

## Phase 2B — observability

An operational audit log records startup, broker reads, and market-data jobs. Decision traces have a schema. The dashboard shows those real records and truthful empty states.

## Phase 3 — Quant Research Lab

One event-driven daily backtest engine, a pre-registered SPY time-series momentum hypothesis (price-only), three benchmarks, chronological train/validation/test reporting, decision replay, research CLI/API, and a Research Lab dashboard. Results are labeled backtests. They are not paper fills and not statistical claims.

## Phase 3.1 — scientific trust layer

Cost accounting charges spread and slippage once. Open timestamps use America/New_York. Replay recomputes from the stored bars. Experiment ids are immutable. `nomadquant-research verify` reports PASS, FAIL, NOT_EVALUABLE, or INVALID_ARTIFACT. Statistical significance stays NOT_EVALUABLE.

## Phase 3.2 — premium research terminal UI

Cohesive dark trading workstation: Command Center, Market Explorer (real SIP daily candles via TradingView Lightweight Charts), Research Lab (date-aligned Recharts equity/drawdown), Decision Intelligence, searchable Activity with histograms, and controlled TanStack Query refresh. Read-only chart API `GET /api/market-data/bars`.

## Phase 4A — local AI research agents

Sequential Researcher → Skeptic → Reviewer on one local Ollama model with read-only tools, claim verification, SQLite agent-run history, CLI (`nomadquant-agent`), and an Agents monitoring page. Retrospective reviews only. No broker tools. No autonomous scheduling.

## Phase 4B — Ollama model benchmarking and agent reliability (current)

Measured local benchmarks (`nomadquant-agent benchmark`), live market-fingerprint checkpoint invalidation, memo overflow rejection, and Agents UI inventory / claim / benchmark panels. Recommended daily model is chosen from measured latency and structured-output reliability, not parameter count.

## Phase 5A — independent risk policy lab (current)

Deterministic `RiskEngine` against the internal $100 ledger only. Verdicts are APPROVE / REJECT / INSUFFICIENT_DATA for hypothetical proposals. CLI `nomadquant-risk`, append-only SQLite audit, and a Risk Policy Lab dashboard. No Alpaca order path.

## Phase 6A — daily shadow research cycle (current)

Persistent $100 shadow ledger, `nomadquant-shadow cycle`, next-session-open simulated fills, and Shadow Portfolio dashboard. Still no Alpaca order path. Dry-run execution gateway contracts exist for a later milestone.

## v1.0 scope freeze

v1.0 is the local research and supervised shadow workstation. Autonomous brokerage trading, strategy optimization, and new models are out of scope. See [V1_LIMITATIONS.md](V1_LIMITATIONS.md).

## Release candidate 1.0.0-rc.1

The local research and shadow scope is frozen. Verifier statuses have distinct exit codes. Quote retrieval time is checked on its own. Pilot readiness names an operational state and does not treat a start timestamp as a running worker. Full-history counts come from SQLite. A pilot preview hash must still match before any later shadow-apply, and preview itself does not mutate the ledger. Remaining limits are listed in [RELEASE_BLOCKERS.md](RELEASE_BLOCKERS.md).

## Phase 5B — paper order gateway (next, separate decision)

Only after risk enforcement is reviewed: an explicitly disabled-by-default Alpaca paper-execution gateway with reconciliation and idempotency. Never given unrestricted LLM tools.

## Explicitly out of scope until a separate decision

- Live trading
- Options, shorts, and leverage
- Copying Lean, NautilusTrader, or vectorbt into this repository
- Any statement that a backtest is realized profit
