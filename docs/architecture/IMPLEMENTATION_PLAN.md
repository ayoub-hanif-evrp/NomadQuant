# Implementation plan

The review after `a927831` is the source of this list. Later phases that were not fully specified are not invented here.

## Done in this repair

| Item | Acceptance |
| --- | --- |
| Marks before a new daily order | A held strategy or connectivity quantity without a trusted bid/ask refuses with `portfolio_unreconciled`. A marked strategy long can pass a later SELL. |
| Partial and cancelled fills | A cancelled sell that filled 0.4 of 1 share leaves 0.6. A second copy of that order does not apply the fill again. |
| One sell quantity | The risk proposal and the broker request both use the strategy-owned share quantity. The sell request carries `qty` and no notional. |
| Durable peak | Equity 110 then 90 keeps peak 110. |
| Price binding | The stored fingerprint names one feed and `alpaca|raw|1Day`. A missing bar, a close mismatch, or a bar published after the decision refuses. A second stored feed does not. |
| Read-only status | `paper_status` does not rewrite fills. `reconcile_paper_orders` does, including prepared and cancelled rows, and it pages FILL activities for that broker order only. |
| Exit precedence | An eligible SELL is the primary action ahead of a new BUY. |
| Loss stop versus exit | A strategy loss stop blocks a new BUY. It does not replace the kill switch, and it does not by itself forbid a strategy SELL. |

Stopping new orders does not cancel an existing broker order and does not sell a position. Recovery is: leave the kill switch engaged, run `reconcile_paper_orders` from a local operator script or test, read `paper_status`, and only then consider a new authorization. Do not resend an order whose broker state is unknown.

## Not done

These remain because they need their own evidence, not because the P0 defects were left in place.

- Split `paper_pilot.py` into transport, lifecycle, reconciliation, and authorization modules.
- Split `apps/web/lib/api.ts` by domain.
- Add the five dashboard views, reusing the current chart components.
- Add a versioned raw, split-adjusted, and dividend-adjusted snapshot with corporate actions. Do not rewrite the existing raw price-only experiments.
- Add a qualification report with the named states. Do not treat that report as permission to trade.
- Compare the deterministic baseline with the AI filter on identical timestamps. No live Ollama session has been run.
- Add opt-in read-only adapters for FRED/ALFRED or SEC EDGAR. Do not put Alpaca's order-capable MCP server on the agent path.
- Audit `docs/ui-shots/` and move superseded captures out of the tree only after a visual-regression check.

## Authorization that was not used

`AUTHORIZE_DAILY_PAPER_PILOT` was not called. `DISABLE_ALPACA_PAPER_ORDERS` remains the emergency stop.
