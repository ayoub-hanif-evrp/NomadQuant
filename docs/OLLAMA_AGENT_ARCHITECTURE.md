# Local Ollama research agents

Phase 4A implements a sequential, auditable research review. It does not trade.

## Machine

- CPU: Intel i7-13700
- GPU: NVIDIA RTX A2000 12 GB
- RAM: 16 GB
- OS: Windows
- Inference: local Ollama only (`http://127.0.0.1:11434`). No paid API.

One model, three sequential roles. Do not load multiple large models at once.

## Roles

1. **Researcher** inspects one stored research run, reads tools, and emits structured claims with evidence refs.
2. **Skeptic** challenges overfitting, significance, costs, dividends, and look-ahead / pretraining contamination.
3. **Reviewer** must call `verify_backtest`, rejects unsupported claims via the deterministic claim checker, and emits a final verdict.

Allowed verdicts: `evidence_supported`, `insufficient_evidence`, `verification_failed`, `research_incomplete`.

A positive backtest return is never an investment recommendation.

## Default model selection

On this workstation `qwen3.5:9b` is installed and is the preferred default for structured tool use. Other installed models may be passed with `--model`. Measure latency on each machine before treating a model as approved.

## Controls

- Structured JSON outputs validated with Pydantic
- SQLite checkpoints (`data/agents.sqlite`) with model id, prompt version, tool schema version, dataset fingerprint
- Tool call budgets, timeouts, cancellation via interrupt where supported
- Audit rows for tool attempts (secrets redacted)
- Runtime-enforced `as_of` cutoff
- Claims about returns must match stored metrics or be marked failed
- Historical LLM use is labeled **retrospective** — not evidence the model could have predicted the market

## Tools

Allowlisted only:

- `read_market_data`
- `inspect_data_quality`
- `read_experiment`
- `read_run_card`
- `verify_backtest`
- `list_research_evidence`
- `save_research_memo`

No shell, web, Alpaca credentials, or order methods.

## CLI

```powershell
uv run nomadquant-agent status
uv run nomadquant-agent run --research-run-id 2 --model qwen3.5:9b
uv run nomadquant-agent inspect --run-id 1
uv run nomadquant-agent resume --run-id 1
```

## Dashboard

`/agents` is a read-only monitoring console. Runs are started from the CLI in this phase.
