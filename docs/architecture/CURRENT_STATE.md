# Current state

Reviewed against commit `a927831` and the repair that followed it. This describes the code, not a promise of profit.

## What can place a paper order

Only Python functions call Alpaca `submit_order`. There is no HTTP route whose path contains `order`.

- `submit_connectivity_order` — the completed $5 SPY connectivity buy. Repeat calls return the existing broker record.
- `submit_strategy_paper_order` — refuses `spy_tsmom_12_1` before any other check.
- `submit_daily_paper_order` — the daily ETF path. It requires the shared emergency stop to be clear, an unexpired daily authorization, a stored decision, and a risk approval.

`paper_status` reads the broker and the local ledger. It does not submit and, by default, it does not write fills back. `reconcile_paper_orders` is the explicit refresh.

`GET /api/paper/status` and `GET /api/daily/status` do not submit and do not reconcile.

## Portfolio truth

`daily/portfolio.py` is the allocated $100 projection. It separates connectivity quantity from strategy quantity. A fill changes cash, quantity, cost, and realized P&L once, including a partial fill on a later cancelled or expired order. Repeating the same client order id does not apply the fill twice.

Valuation uses a supplied mark. A missing mark sets `valuation` to `unavailable` and does not treat cost basis as a market price. Strategy loss is realized plus marked P&L, and it blocks a new BUY at $20. A SELL of strategy-owned shares can still be risk-checked while that stop is active. The kill switch blocks both.

`note_equity` stores the high-water mark. A later lower equity does not replace it. The first recorded peak is at least the $100 allocation.

## Decision binding

`evaluate_daily` stores the strategy version, both policy versions, and a fingerprint of the closes it used. Submission refuses a different series. If `data/market.sqlite` already contains a close for that session and the close differs, submission refuses. An empty store cannot confirm the series.

The trend rule does not buy again while that strategy already holds the target. A risk-reducing SELL is chosen ahead of a new BUY.

## What is still not true

- The daily pilot is not authorized. `ALLOW_ORDER_SUBMISSION` remains false. No Windows task is installed.
- Passing tests are not a complete broker lifecycle. Partial-fill accounting is covered with local order rows. It has not been replayed against a live Alpaca partial.
- Official Alpaca, FRED, EDGAR, and other external MCP servers are not connected. Agents only see the in-process read-only tool list.
- `apps/web/lib/api.ts` and `broker/paper_pilot.py` are still large modules. They were not split in this repair.
- The five dashboard views named in the review (Portfolio Truth, Strategy Validation, Execution Audit, Data Quality, System Readiness) are not separate pages.
- There is no new statistical qualification lab. Existing research reports stay historical. They do not authorize an order.
