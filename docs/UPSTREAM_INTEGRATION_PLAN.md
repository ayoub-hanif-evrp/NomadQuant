# Upstream integration plan

NomadQuant did not vendor or translate source from these repositories. The notes below are design lessons. Fincept licensing is inconsistent (AGPL text plus extra commercial and trade-dress terms); no Fincept code is reused. Vibe-Trading is MIT and TradingAgents is Apache-2.0. Because no source files were copied, no additional NOTICE file is required for this phase. A later copy of MIT or Apache code must keep that project's copyright notice.

Machine budget: 16 GB RAM, RTX A2000 12 GB. New work in this phase is CPU-only SQLite and Python. No extra model is loaded.

## Vibe-Trading (MIT)

| Concept | File | Decision | Why |
| --- | --- | --- | --- |
| Run card / manifest | `agent/backtest/run_card.py` | Implement now | Each NomadQuant run needs an immutable, labeled backtest card. |
| Validation verdicts | `agent/backtest/validation.py` | Implement now | PASS / FAIL / NOT_EVALUABLE / INVALID_ARTIFACT. Missing evidence is not a pass. |
| Metric honesty | `agent/backtest/metrics.py` | Implement now | Undefined ratios stay null. Sortino is not a stdev of losers only. |
| Evidence objects | `agent/src/agent/grounding/evidence.py` | Implement now, narrower | Decisions store recomputed features and a hash. Replay recomputes from bars. |
| Eval harness | `agent/evals/harness/assertions.py` | Implement now | `nomadquant-research verify` is the local harness. |
| Evidence store | `agent/src/strategy_discovery/evidence_store.py` | Later | Full claim graphs wait until agents exist. |
| Their backtest framework | package as a whole | Reject | NomadQuant keeps its own engine. |

## TradingAgents (Apache-2.0)

| Concept | File | Decision | Why |
| --- | --- | --- | --- |
| Role split: researcher / skeptic / reviewer | `tradingagents/graph/setup.py` | Document now, implement later | Sequential roles fit 16 GB RAM. Do not load three models. |
| Typed agent state | `tradingagents/agents/schemas.py` | Later | Needed when Ollama runs. |
| Tool bounds and date windows | `tradingagents/dataflows/date_window.py`, `agents/tools.py` | Implement now as a registry | Read-only tools reject `as_of` violations. No order tools. |
| Checkpoints | `tradingagents/graph/checkpointer.py` | Later | Crash resume belongs with the agent loop. |
| Memory log | `tradingagents/memory/log.py` | Later | Prompt logs come with the first real agent run. |
| Full LangGraph runtime | `trading_graph.py` | Reject for this phase | Too heavy, and agents are not executed yet. |

## FinceptTerminal

| Concept | File | Decision | Why |
| --- | --- | --- | --- |
| Modular boundaries | `docs/ARCHITECTURE.md` | Already in NomadQuant | Keep packages, not a copied UI. |
| Decision replay tables | `docs/ALPHA_ARENA.md` | Implement now, offline only | Replay simulated research decisions. No venue, no kill-switch trading. |
| Typed tool permissions | `fincept-qt/docs/MCP_TOOLS_GUIDE.md` | Implement now, small | A Python registry, not MCP/C++. |
| Their source, layout, or marks | repository | Reject | License conflict and trade-dress terms. |

## This phase versus later

Now: cost accounting, New York timestamps, independent replay, immutable experiment ids, run cards, verifier, read-only tool registry, dashboard trust labels.

Later: one local Ollama process, sequential researcher → skeptic → reviewer, checkpoints, and a comparison against the non-LLM baseline. No broker tool.
