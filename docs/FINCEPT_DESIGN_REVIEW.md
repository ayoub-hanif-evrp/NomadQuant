# Fincept design review

This note records what NomadQuant took as **architectural inspiration** from public Fincept Terminal documentation, and what it deliberately did **not** copy. No Fincept source file was vendored, translated, or imported. NomadQuant’s UI, schemas, and backtest code are original.

References consulted (read-only, documentation and directory listings):

- [Fincept ARCHITECTURE.md](https://github.com/Fincept-Corporation/FinceptTerminal/blob/main/docs/ARCHITECTURE.md)
- [Alpha Arena](https://github.com/Fincept-Corporation/FinceptTerminal/blob/main/docs/ALPHA_ARENA.md)
- [Agentic research README](https://github.com/Fincept-Corporation/FinceptTerminal/blob/main/fincept-qt/docs/agentic-research/README.md)
- [MCP tools guide](https://github.com/Fincept-Corporation/FinceptTerminal/blob/main/fincept-qt/docs/MCP_TOOLS_GUIDE.md)
- Directory listing of `fincept-qt/scripts/Analytics/backtesting/` (wrappers around third-party engines; not used here)
- Fincept `LICENSE` (AGPL-3.0 with additional commercial and trade-dress terms)

## Useful architectural concepts

| Idea | Why it matters for NomadQuant |
| --- | --- |
| Modular monolith with clear package boundaries | Matches NomadQuant’s existing layout: one FastAPI process, one dashboard, packages instead of microservices. |
| Append-only audit / replay from durable rows | Alpha Arena stores ticks, prompts, decisions, fills, and rebuilds history from SQLite. NomadQuant needs the same fidelity for **simulated** research decisions. |
| Separate paper simulation from live/broker paths | Paper is a simulator with explicit assumptions, not a degraded live path. NomadQuant’s backtest must stay offline and never call Alpaca order APIs. |
| Risk as an independent gate | Fincept’s risk engine accepts/rejects/amends before routing. NomadQuant already reserves `RiskEngine` for a later paper-order phase; research simulation records capital constraints but does not submit orders. |
| Typed tool schemas and destructive-action gating | Relevant later for agents. Phase 3 does not add MCP or LLM tools. |
| SQLite checkpointing for long-running work | Useful later for agents. Phase 3 only needs experiment/run persistence and restart-safe evidence. |

## What NomadQuant already implements

- Paper-only settings lock and read-only Alpaca account/positions
- Historical daily OHLCV store for SPY/QQQ with feed labeling and coverage checks
- Operational audit events, runs, and decision-trace schema
- Monitoring dashboard (health, activity, runs, market data)
- Research standards documenting Moskowitz et al., Bailey & López de Prado, and mandatory benchmarks
- `BacktestEngine` / `Strategy` protocols (unimplemented until this phase)

## What belongs in this phase

- Audit fidelity fixes (valid JSON payloads, artifacts for large evidence, merge-safe run completion)
- Experiment registry with immutable configuration and trial history
- One event-driven daily backtest engine ($100, long-only, fractional shares, costs, next-open execution)
- One pre-registered SPY time-series momentum hypothesis (price-only mode)
- Three benchmarks under the same assumptions
- Chronological train / validation / locked-test reporting (no parameter search)
- Decision traces + deterministic replay for simulated decisions
- Research CLI, read-only research API, and a Research Lab dashboard page

## What waits for later phases

- LLM / agent execution, MCP tools, and agent-to-broker wiring
- Real paper order submission, cancellation, liquidation
- Full economic-return mode with verified dividends and splits (requires additional free data provenance)
- Multi-strategy optimization platforms, walk-forward parameter grids
- GPU / local LLM inference

## Licensing and dependency risks

Fincept’s repository advertises AGPL-3.0-or-later while the same `LICENSE` file adds commercial-use restrictions, trade-dress claims, and dual-licensing language. Those terms are inconsistent with a clean “AGPL-only” reading. Regardless of interpretation:

1. **Do not copy Fincept code, UI layouts, trade dress, or trademarks into NomadQuant.**
2. **Do not create a derivative of Fincept’s backtesting wrappers** (the tree lists `backtesting.py`, `bt`, `vectorbt`, `zipline`, and others). NomadQuant implements its own engine against `BacktestEngine`.
3. NomadQuant remains proprietary all-rights-reserved. Importing AGPL-covered Fincept code would create license conflict and is rejected.
4. Third-party engines Fincept wraps (for example vectorbt’s Commons Clause) were already declined in [DEPENDENCY_REVIEW.md](DEPENDENCY_REVIEW.md).

Scientific citations used by NomadQuant (Moskowitz, Ooi & Pedersen 2012; White 2000; Bailey & López de Prado 2014) are separate academic references and do not imply Fincept affiliation.
