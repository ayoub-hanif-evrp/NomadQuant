# Capability matrix

Versions refer to the behavior in the working tree after the portfolio-truth repair. Historical documents that say no paper order can exist describe v1 research boundaries. Those sentences are superseded by this matrix.

| Capability | State | Notes |
| --- | --- | --- |
| Live-money trading | Unavailable | `TRADING_MODE=paper`. A live URL or `ALLOW_ORDER_SUBMISSION=true` fails settings load. |
| HTTP order route | Unavailable | Route safety rejects any path containing `order`. |
| Alpaca paper connectivity buy | Retired | `nq-connect-spy-buy-5` filled. It stays in the account, uses the $100 sleeve, and is not strategy P&L. |
| Monthly `spy_tsmom_12_1` paper submission | Retired | Research code remains. Submission returns `retired_monthly_strategy`. |
| Daily ETF paper pilot | Disabled | Code exists. It does not run until `AUTHORIZE_DAILY_PAPER_PILOT`. The kill switch blocks it. |
| Emergency stop | Available | `DISABLE_ALPACA_PAPER_ORDERS` stops connectivity, monthly, and daily submission. It does not cancel or liquidate. |
| Paper status read | Available | `GET /api/paper/status` does not submit and does not rewrite the local ledger. |
| Explicit paper reconcile | Available | `reconcile_paper_orders` in the Python broker module. Not an HTTP route. |
| $100 allocation ledger | Available | Connectivity and strategy quantities are separate. Missing marks leave valuation unavailable. |
| Strategy loss stop | Available | $20 of marked strategy P&L blocks a new BUY. A strategy SELL still requires authorization, a mark, and the risk engine. |
| Equity high-water mark | Available | Stored in the daily SQLite file. It is not reset to the latest equity. |
| Read-only daily MCP tools | Available | In-process server only. Order tools are not listed. |
| External Alpaca, FRED, EDGAR, or other MCP servers | Unavailable | Not installed. Alpaca's server can place orders, so it is not an agent tool. |
| Ollama daily adapter | Experimental | Fail-closed when the model is down. Not demonstrated against a live model in this repair. |
| Shadow and research backtests | Available | Historical research. They do not submit paper orders. |
| Unattended Windows schedule | Unavailable | No daily or shadow task is installed by this repair. |
| Dashboard views for truth, validation, audit, data quality, and readiness | Available | The paper page has those sections and shows `research_evidence`. `apps/web/scripts/operator-browser.mjs` opens paper, agents, health, research, and market data. |
| Strategy qualification | Not granted on stored data | The locked gates can return `RESEARCH_QUALIFIED` for an announcement-vintage total-return series. Raw prices and Alpaca `process_date` files stay `NOT_EVALUABLE`. That label is not permission to trade. |
