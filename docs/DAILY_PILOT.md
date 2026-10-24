# Daily AI paper pilot

The active paper design is a daily ETF pilot. It is not authorized to submit orders.

The monthly `spy_tsmom_12_1` rule remains available for historical research. New Alpaca paper orders for that strategy are refused with `retired_monthly_strategy`. Its old results are not rewritten.

The filled connectivity order `nq-connect-spy-buy-5` / `e9bab439-11e8-4814-aeca-9c170544cfa3` is not a strategy holding and is not sold by this pilot. Its cost still reduces the shared $100 sleeve.

## Strategies

`etf_trend_sma_v1` follows Faber (2007) and the moving-average evidence in Brock, Lakonishok, and LeBaron (1992). A buy requires the latest available close to be above the 200-session average and 20-session daily volatility at or below 2 percent. Otherwise the strategy is in cash. The parameters were declared in advance and were not fit to maximize a backtest.

`etf_reversal_5d_v1` is a restricted reading of Jegadeesh (1990) and Lehmann (1990). Index ETFs diversify the stock-level effect, so a buy also requires the close to remain above the 200-session average and a five-session decline of at least 1.5 trailing dispersions. It does not buy when the trend strategy is already buying, when price is below the average, or when daily volatility exceeds 2.5 percent.

Both rules use only sessions available after 16:30 America/New_York and, when authorized, would trade on the next regular session. A missed session is recorded and is not submitted late. HOLD is a normal outcome. An existing long position is not bought again while the target stays long. A cash target sells only shares the strategy itself holds.

Walk-forward output is labeled `historical_research` and `hypothetical_not_broker`. It is not prospective paper performance.

## Agents and MCP

The technical analyst, news analyst, strategy researcher, skeptic, and portfolio agent read a read-only MCP server named `nomadquant-daily-readonly`. The server is called through the official MCP client session. Tool results are untrusted data. There is no submit, cancel, or withdraw tool.

Influence policy `daily_agent_influence_1.0.0` lets the skeptic force HOLD and lets material news uncertainty cut a buy in half. Agents cannot create a buy the deterministic rule did not emit, change the symbol, or override the risk engine. If the model is missing or invalid, the AI path fail-closes to HOLD. The deterministic baseline is stored beside it and is not sent to Alpaca.

## Authorization

Submission stays off until this exact phrase is used with a duration of 1 to 30 calendar days:

`AUTHORIZE_DAILY_PAPER_PILOT`

`DISABLE_ALPACA_PAPER_ORDERS` is the emergency stop for the connectivity route, the retired monthly route, and the daily route. A daily kill also stops the older routes. No Windows task is installed. `scripts/daily-ai.ps1` prints the local desk status and does not submit. The computer would have to be on for any later local schedule.

Strategy loss uses realized plus marked-to-market P&L on strategy holdings. A difference between requested notional and fill value is not a loss. A missing mark leaves valuation unavailable and blocks a new buy; it is not stored as a zero price. The loss stop blocks new buys. It does not cancel an open broker order, liquidate a position, or override the kill switch. A strategy sell still needs authorization, a mark, and the risk engine.

`GET /api/paper/status` does not rewrite local fills. `reconcile_paper_orders` is the explicit refresh. A sell is sent as a share quantity, floored to nine decimal places, and that same quantity is the one the paper risk check sees. Any remainder stays tracked and is not rounded up into the order. Daily realized P&L uses individual FILL activities for that broker order, paged with `order_id` and `page_token`. An order's creation time is not a fill time. A completion-time average is an aggregate estimate and is not assigned to one session. A sell with no verified execution timestamp leaves the session figure unverified. Incomplete or conflicting fill history is `execution_history_incomplete` or `journal_disagreement`. That state blocks a new BUY and still allows an authorized strategy SELL when the position itself is not disputed. `nomadquant-shadow paper-verify` compares the local ledger with Alpaca and does not submit, authorize, or rewrite history. Reconciliation also revisits prepared and cancelled orders and does not send a second order when the broker outcome is unknown. Lifetime realized P&L is kept separately. A loss or drawdown breaker blocks a new buy and still allows a verified strategy sell. Every holding is marked before that check. Submission requires the decision's own feed, `alpaca|raw|1Day`, to contain every close, available at the decision time. Another feed in the store is not a conflict. The equity peak is stored and is not replaced by a later lower equity. The paper quantity policy is `1.3.0`; the historical research policy remains `1.2.0`.

Post-trade email is queued after a decision. Without SMTP, the notice stays `not_configured` and is not described as delivered.

## Supervised forward session

This section does not authorize a session. Do it only with a separate explicit decision.

1. Run `nomadquant-shadow paper-verify`. Read `next_action`. Broker cash is the whole paper account. The sleeve is the internal $100 allocation. The command does not submit.
2. Leave the pilot off until `AUTHORIZE_DAILY_PAPER_PILOT`, for 1 to 30 days.
3. A strategy order is a market order during the session. A next-close research fill is not that order.
4. After any fill, `reconcile_paper_orders` is the write that journals it. `paper-verify` only reads. Repeated reads must stay `history_rewritten` false and `broker_orders_submitted_by_this_request` false.
5. `DISABLE_ALPACA_PAPER_ORDERS` stops new submissions. It does not cancel or sell.
6. One connectivity fill, even when the journal matches, is not `PAPER_VALIDATED`.

