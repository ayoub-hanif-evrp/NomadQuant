# Project completion

NomadQuant is a local, paper-only research workstation. Three claims stay separate. A passing test does not prove a strategy, and a matched connectivity fill does not prove a supervised paper strategy.

## Release states

| State | Result | What remains |
| --- | --- | --- |
| `ENGINEERING_READY` | Granted | `.\scripts\release-check.ps1` passed on this PC on 2026-10-24: Python 3.12, uv, Node, lockfiles, ruff, mypy, 458 pytest tests, eslint, TypeScript, and the browser check. Tests used temporary databases and did not open `.env`. GitHub Actions run 40106555100 on `8774de0` passed, including the Linux browser step and Windows smoke. A wiped second PC was not reinstalled. |
| `RESEARCH_QUALIFIED` | Not granted | The 85 local SPY and QQQ dividends have process dates and no announcement times. The synthetic series that cleared the gates is not SPY or QQQ. Research fills are the next close, not an intraday paper market order. |
| `PAPER_VALIDATED` | Not granted | The existing $5 connectivity fill now has one local execution row, and a read-only check is healthy. No supervised strategy session has been run. |

## What was run on 2026-10-24

`reconcile_paper_orders` wrote the missing local execution for `nq-connect-spy-buy-5`. It did not submit an order. The following read-only check reported:

- readiness healthy
- broker orders submitted by that read: false
- authorization unchanged
- SPY position matched
- portfolio verified
- one execution row for `nq-connect-spy-buy-5`

`.\scripts\doctor.ps1` passed for Python 3.12, uv, Node, the web build, the local databases, the API, the dashboard, and Ollama's tag endpoint. No secret was printed.

`.\scripts\release-check.ps1` then passed: ruff, mypy on 149 source files, 458 pytest tests, eslint, TypeScript, and `npm run operator-browser`. The browser check covered the paper page, home navigation, agents, health, research, and market data, on desktop and a 390-pixel paper page. It did not submit an order. The same command did not read `.env` or the live SQLite files.

GitHub Actions run [40106555100](https://github.com/ayoub-hanif-evrp/NomadQuant/actions/runs/40106555100) on `8774de0` completed successfully. The Linux job's browser step and the Windows smoke job both passed. That run does not include the tests added after `8774de0`.

## What the code has proved

- Research, risk, shadow accounting, and the daily ETF rules.
- Read-only MCP tools. A missing model fail-closes and is not a useful veto.
- Paper submission controls, the $100 sleeve, the emergency stop, fractional sells, paged fills, and the execution journal.
- One offline buy, partial fill, restart, loss stop, protective sell, and kill switch.
- Two processes cannot both claim the same prepared row. A second process cannot claim a row left `unknown` after an uncertain submission.
- A paper verification with no Alpaca credentials is `blocked` / `credentials_absent` and does not create a paper database. The report states that the $100 sleeve is not broker cash.
- A price changed after the locked fingerprint is `NOT_EVALUABLE`. A missing model comparison is `NOT_MEASURED`.
- Corporate actions stored apart from raw bars.
- Qualification gates that can fail, with `permission_to_trade` false.

## What is still not proved

- An edge for the ETF rules.
- That a next-close backtest matches an intraday Alpaca market fill.
- A supervised forward paper session. The daily pilot stays off.
- A wiped second computer. The automated check used this PC's existing install and temporary databases.
- Historical Ollama decisions. None were invented.

## What the operator can run

```powershell
.\scripts\release-check.ps1
uv run --no-sync nomadquant-shadow paper-verify
```

`release-check.ps1` is the release gate. It does not grant `RESEARCH_QUALIFIED` or `PAPER_VALIDATED`. The supervised session procedure is in `docs/DAILY_PILOT.md`.

## Decisions this document does not make

1. Broker cash and buying power are not the $100 sleeve.
2. The daily pilot stays off until `AUTHORIZE_DAILY_PAPER_PILOT`, for 1 to 30 days.
3. `DISABLE_ALPACA_PAPER_ORDERS` stops new submissions. It does not cancel or sell.
4. Do not install `NomadQuantShadowDaily` or the automatic pilot.

## Unsupported

Live-money trading, leverage, shorting, options, unattended orders, order-capable MCP servers, FRED, EDGAR, and a claim that any strategy has a statistical edge.

## Next action

Leave the daily pilot off. A supervised session starts only with a separate `AUTHORIZE_DAILY_PAPER_PILOT`, for 1 to 30 days, then a read-only `paper-verify` after any fill. This document does not authorize that phrase. The open research fact is still the missing announcement time on the dividend file.
