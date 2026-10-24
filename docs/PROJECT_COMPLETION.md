# Project completion

NomadQuant is a local, paper-only research workstation. This note separates three claims. Passing tests do not make a strategy qualified, and a qualified backtest would not make the Alpaca paper account validated.

## Release states

| State | Result | Why |
| --- | --- | --- |
| `ENGINEERING_READY` | Not granted | The paper path covered by the suite does what its tests say. Corporate-action datasets, a browser suite, a clean-install rerun, and a live broker lifecycle are still open. |
| `RESEARCH_QUALIFIED` | Not granted | Registered ETF rules run on raw prices. `qualify_daily_strategies` returns `NOT_EVALUABLE` because split and dividend history is not stored. |
| `PAPER_VALIDATED` | Not granted | `nomadquant-shadow paper-verify` is read-only. The last live read found the connectivity SPY position and no local execution row for `nq-connect-spy-buy-5`. That report was unverified. This pass did not call Alpaca. |

## What is implemented

- Research, risk, shadow accounting, and the daily ETF rules.
- Read-only MCP tools and an Ollama path that fail-closes when the model is down.
- Paper submission with the $100 sleeve, the emergency stop, fractional sells, paged fills, and an execution journal.
- A read-only verifier: `nomadquant-shadow paper-verify`.
- Offline evidence in `tests/test_project_completion.py`: one buy, one partial fill, no second buy after restart, a loss stop, one protective sell, then the kill switch.
- Dataset and AI labels that refuse a qualification the data cannot support.

## What the operator can run

From the repository root, after `uv sync`:

```powershell
$env:PYTHONPATH="src"
uv run --no-sync ruff check .
uv run --no-sync mypy src
uv run --no-sync pytest -q
uv run --no-sync nomadquant-shadow paper-verify
```

`paper-verify` reads the paper account and writes nothing. It does not authorize the daily pilot. Start and stop the workstation with `.\scripts\start-nomadquant.ps1` and `.\scripts\stop-nomadquant.ps1`.

## Supervised paper checklist

Do these only with a separate explicit decision. This document does not authorize them.

1. Read `paper-verify`. Do not treat broker cash or buying power as the $100 sleeve.
2. If the report is unverified because a known fill has no journal row, decide whether to run `reconcile_paper_orders`. That writes the local journal. It does not submit.
3. The daily pilot stays off until `AUTHORIZE_DAILY_PAPER_PILOT`, for 1 to 30 days.
4. `DISABLE_ALPACA_PAPER_ORDERS` stops new submissions. It does not cancel or sell.
5. Do not install `NomadQuantShadowDaily` or the automatic pilot.

## Unsupported

Live-money trading, leverage, shorting, options, unattended orders, order-capable MCP servers, FRED, EDGAR, and a claim that any strategy has a statistical edge.

## Next action

Read the latest `paper-verify` output. Leave authorization off until that report is understood. Do not reconcile or submit unless that is a separate decision.
