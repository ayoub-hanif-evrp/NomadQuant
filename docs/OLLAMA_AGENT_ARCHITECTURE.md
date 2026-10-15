# Future local Ollama research agents

This is a design note. NomadQuant does not call Ollama in this phase. No agent run exists.

## Machine

- CPU: Intel i7-13700
- GPU: NVIDIA RTX A2000 12 GB
- RAM: 16 GB
- OS: Windows
- Inference: local Ollama only. No paid API.

Loading three separate 9B–14B models at once is a poor fit for 16 GB of system RAM plus a 12 GB GPU. The workflow is one model, three sequential roles.

## Roles

1. **Researcher** writes a falsifiable hypothesis, the data window, and the citations. It may call read-only tools.
2. **Skeptic** challenges costs, look-ahead, dividends, and whether the locked test was touched. It uses the same model and the same tools.
3. **Reviewer** calls `verify_backtest` and may only summarize tool results. It cannot override a FAIL.

A valid outcome is `insufficient_evidence`.

## Candidate models

- `qwen3.5:9b`
- `qwen3:14b`, only if a later measurement shows it fits GPU memory and leaves the API responsive

Neither model is approved until memory, structured-output reliability, tool-call behavior, and latency are measured on this PC.

## Controls when the loop is built

- Structured inputs and outputs
- SQLite checkpoints that record model id, prompt version, tool schema version, and dataset fingerprint
- A maximum number of tool calls and iterations
- Timeouts and cancellation
- A context limit
- An audit row for every prompt and tool call, with secrets redacted
- Claims about returns must match deterministic metrics or be marked unverified
- Historical LLM use must say that pretraining may have seen the same public prices

## Tools the loop may receive

The registry in `nomadquant.research.tools` exposes:

- `read_market_data` (requires timezone-aware `as_of`; end cannot pass the cutoff)
- `inspect_data_quality`
- `read_experiment`
- `read_run_card`
- `verify_backtest`
- `list_research_evidence`
- `save_research_memo` (one markdown filename inside the memo workspace)

It does not expose a shell, a web browser, Alpaca credentials, or any order, cancel, or liquidate method. A risk rejection, once a risk engine exists, is not overridable by the model.

## Evaluation

The non-LLM baseline remains the pre-registered SPY time-series momentum rule and the buy-and-hold / cash benchmarks. An agent is not promoted because a backtest, or a memo, looks persuasive.
