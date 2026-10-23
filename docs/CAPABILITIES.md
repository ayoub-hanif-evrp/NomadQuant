# Capabilities

This is the current inventory. Internal paper-order functions exist. HTTP order routes and unattended schedules are not enabled.

| Capability | State |
| --- | --- |
| Live-money trading | Unsupported |
| HTTP route that submits an order | Unsupported |
| Unattended Windows task | Unsupported |
| Alpaca paper order functions in Python | Disabled until `AUTHORIZE_DAILY_PAPER_PILOT` |
| Emergency stop `DISABLE_ALPACA_PAPER_ORDERS` | Active |
| Filled connectivity buy `nq-connect-spy-buy-5` | Active ledger fact, not strategy performance |
| Monthly `spy_tsmom_12_1` research | Active for historical replay |
| Monthly paper submission | Deprecated. Returns `retired_monthly_strategy` |
| Daily trend and reversal research rules | Active and versioned. Not authorized to trade |
| $100 internal allocation | Active |
| Read-only in-process MCP tools | Active |
| External Alpaca, FRED, EDGAR, Financial Datasets, or GitHub MCP servers | Unsupported in this repository |
| Ollama daily adapter | Experimental. Fail-closed when the model is absent |
| Playwright package in the web app | Present for development. No trading-desk browser suite is wired into CI |
| Five named research dashboards as separate apps | Unsupported. The paper page contains the trust sections |

See `docs/MCP_EVALUATION.md` for the external servers that were reviewed and not installed.
