# Current state

Reviewed against the daily paper desk as of the execution-journal repair. This describes the code, not a promise of profit.

## What can place a paper order

Only Python functions call Alpaca `submit_order`. There is no HTTP route whose path contains `order`.

- `submit_connectivity_order` — the completed $5 SPY connectivity buy. Repeat calls return the existing broker record.
- `submit_strategy_paper_order` — refuses `spy_tsmom_12_1` before any other check.
- `submit_daily_paper_order` — the daily ETF path. It requires the shared emergency stop to be clear, an unexpired daily authorization, a stored decision, and a risk approval.

`paper_status` reads the broker and the local ledger. It does not submit and, by default, it does not write fills back. `reconcile_paper_orders` is the explicit refresh.

`GET /api/paper/status` and `GET /api/daily/status` do not submit and do not reconcile.

## Portfolio truth

`daily/portfolio.py` is the allocated $100 projection. It separates connectivity quantity from strategy quantity. Cash, quantity, cost, and realized P&L are rebuilt from the append-only `paper_executions` journal. A partial fill on a later cancelled or expired order keeps the executed shares. The same execution id is not applied twice. Daily realized P&L uses a timezone-aware FILL timestamp in America/New_York. Order creation time is not a fill time. An order-level average at `filled_at` is an aggregate estimate and is not assigned to one session. The book reports `verified`, `unverified`, or `disputed`.

Valuation uses a supplied mark. A missing mark sets `valuation` to `unavailable` and does not treat cost basis as a market price. Strategy loss is realized plus marked P&L, and it blocks a new BUY at $20. A SELL of strategy-owned shares can still be risk-checked while that stop is active. The kill switch blocks both.

`note_equity` stores the high-water mark. A later lower equity does not replace it. The first recorded peak is at least the $100 allocation.

## Decision binding

`evaluate_daily` stores the strategy version, both policy versions, the feed (`iex` or `sip`), the dataset `alpaca|raw|1Day`, and a version-2 fingerprint of those closes. Submission refuses a different series, a missing bar, a close mismatch, a naive timestamp, or a bar that was not available at the original decision time. Another feed in the store is not a conflict. An empty store refuses the order.

The trend rule does not buy again while that strategy already holds the target. A risk-reducing SELL is chosen ahead of a new BUY.

## What is still not true

- The daily pilot is not authorized. `ALLOW_ORDER_SUBMISSION` remains false. No Windows task is installed.
- Fill reads for one broker order use Alpaca `order_id` and `page_token`. A failed or unfinished page stays unverified. That paged read has automated tests against a fake client. A live paper-account read is a separate check and is not itself a fill.
- Reconciliation revisits prepared and cancelled orders. The send path claims `prepared` once, rechecks the emergency stop and authorization, and does not submit when the broker outcome is unknown.
- Passing tests are not a complete broker lifecycle. They have not shown a live Alpaca partial fill.
- Official Alpaca, FRED, EDGAR, and other external MCP servers are not connected. Agents only see the in-process read-only tool list.
- `apps/web/lib/api.ts` and `broker/paper_pilot.py` are still large modules. They were not split in this repair.
- The five dashboard views named in the review (Portfolio Truth, Strategy Validation, Execution Audit, Data Quality, System Readiness) are not separate pages.
- There is no new statistical qualification lab. Existing research reports stay historical. They do not authorize an order.
