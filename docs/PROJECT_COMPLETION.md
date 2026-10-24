# Project completion

NomadQuant is a local, paper-only research workstation. Three claims stay separate. A passing test does not prove a strategy, and a matched connectivity fill does not prove a supervised paper strategy.

## Release states

| State | Result | What remains |
| --- | --- | --- |
| `ENGINEERING_READY` | Not granted | The tested path, the two-process claim, the local browser check, and this PC's doctor passed. A from-scratch install and the new GitHub browser job have not run. |
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

`npm run operator-browser` passed against the production build on `127.0.0.1:3010`. Desktop and a 390-pixel viewport both showed the paper page, including the statement that the page does not submit an order.

## What the code has proved

- Research, risk, shadow accounting, and the daily ETF rules.
- Read-only MCP tools. A missing model fail-closes and is not a useful veto.
- Paper submission controls, the $100 sleeve, the emergency stop, fractional sells, paged fills, and the execution journal.
- One offline buy, partial fill, restart, loss stop, protective sell, and kill switch.
- Two processes cannot both claim the same prepared row.
- Corporate actions stored apart from raw bars.
- Qualification gates that can fail, with `permission_to_trade` false.

## What is still not proved

- An edge for the ETF rules.
- That a next-close backtest matches an intraday Alpaca market fill.
- A supervised forward paper session. The daily pilot stays off.
- A clean-machine install.
- Historical Ollama decisions. None were invented.

## What the operator can run

```powershell
$env:PYTHONPATH="src"
uv run --no-sync pytest -q
uv run --no-sync nomadquant-shadow paper-verify
.\scripts\doctor.ps1
```

From `apps/web`, after `npm run build`: `npm run operator-browser`.

## Decisions this document does not make

1. Broker cash and buying power are not the $100 sleeve.
2. The daily pilot stays off until `AUTHORIZE_DAILY_PAPER_PILOT`, for 1 to 30 days.
3. `DISABLE_ALPACA_PAPER_ORDERS` stops new submissions. It does not cancel or sell.
4. Do not install `NomadQuantShadowDaily` or the automatic pilot.

## Unsupported

Live-money trading, leverage, shorting, options, unattended orders, order-capable MCP servers, FRED, EDGAR, and a claim that any strategy has a statistical edge.

## Next action

Leave the daily pilot off. The connectivity journal now matches Alpaca. The open research fact is the missing announcement time on the dividend file. Do not treat that file as point-in-time, and do not authorize a paper session from this document.
