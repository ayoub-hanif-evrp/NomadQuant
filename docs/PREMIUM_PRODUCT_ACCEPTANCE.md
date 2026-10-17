# Premium product acceptance

Checked on 2026-10-17 against the local workstation. This is not a live-trading release.

## What changed

The default navigation is Home, Intelligence, Agents, Markets, Portfolio, Approvals, and Advanced. Home is a chart-centered view of stored SIP daily bars, with the session clock, a freshness strip, shadow cash, the approval inbox, and headlines. Historical research remains under Advanced. It is not presented as current market intelligence.

Nomad Copilot sits on every page. It answers from stored evidence. A local model is used only when its reply does not introduce numbers that are absent from that evidence.

The agent page draws Researcher, Skeptic, Reviewer, and deterministic verification. Nodes stay idle unless a stored or running review says otherwise. Replay of a recorded run is labeled REPLAY. Starting a new review requires an explicit confirmation, an installed model, and a stored research run. It does not download a model and cannot place an order.

News refresh and headline analysis are separate read-only actions. They were not run against the live Alpaca account during this check. The feed therefore shows that news has not been loaded.

Email approval is a POST. GET `/api/approvals/{id}/decide` returns 405. A bound approval can store the existing internal shadow grant. It does not fill the ledger and does not submit an Alpaca order.

## Design

The interface uses the existing midnight surfaces, IBM Plex Sans and IBM Plex Mono, and a teal accent. Primary text is 15px. Delayed data uses a DELAYED badge. Red is reserved for errors.

References used as principles, not copied branding:

- Linear design refresh: https://linear.app/now/behind-the-latest-design-refresh
- Vercel Geist: https://vercel.com/geist/introduction
- shadcn charts: https://ui.shadcn.com/docs/components/radix/chart
- Aceternity: https://ui.aceternity.com/components
- React Flow: https://reactflow.dev/examples/edges/animating-edges
- Motion: https://motion.dev/docs/react
- Lightweight Charts: https://tradingview.github.io/lightweight-charts/tutorials

Charts use the existing TradingView Lightweight Charts component and Recharts. React Flow animates an edge only while a recorded replay is stepping. Motion for React was not added.

## Data provenance

`GET /api/market-data/freshness` at 2026-10-17T11:37:21Z:

- Feed: SIP
- Timeframe: 1Day
- `live`: false
- Entitlement: `historical_daily_bars`
- Eligible completed session: 2026-10-16
- SPY and QQQ latest stored session: 2026-10-15
- Stored sessions: 2209 each
- Missing sessions: 2026-10-16 for each symbol
- Status: `WAITING_FOR_DATA`

The home screen says the stored bar is behind the eligible session. It does not say the feed is live. A page refresh is not a quote.

No market-data sync was started. No IEX quote was written over SIP bars.

## Portfolio

`GET /api/shadow/status`:

- `trading_state`: SHADOW_ONLY
- `allow_order_submission`: false
- cash: 100 USD
- holdings: empty
- ledger version: 1
- cycle count: 2

The portfolio page draws an equity area only when at least two equity points exist. Otherwise it says: "No forward trading results yet. The supervised pilot has not completed a fill."

## Copilot

On the production build, the question "How much virtual money do I currently have?" returned "100 USD". The evidence card was `scope.locks`: trading mode is paper, order submission is disabled, and the internal virtual capital is 100 USD. The model named in the panel was `qwen3.5:9b`. The reply was kept because 100 is present in that evidence. The assistant has no broker-order tool.

Screenshot: `docs/ui-shots/premium-copilot-1280x800.png`.

## Agents

The graph showed "No review is running" before a stored run was opened. Replay of a stored run displayed "REPLAY of a stored run. This is not a live model call." No new Ollama review was started during the browser check. Screenshot: `docs/ui-shots/premium-agents-replay-1280x800.png`.

## News

`GET /api/news/headlines` returned `not_loaded` and an empty list. No article body was stored. Entitlement to the Alpaca News API was not probed, because refresh is an explicit network call and was not clicked. The interface does not substitute example articles.

## Approvals

A live GET of `/api/approvals/scanner/decide` returned 405. Pytest covers the POST path: a missing mutation header leaves the request pending; an unbound approval records permission and does not issue a shadow grant; a bound approval calls `confirm_pilot_start` and still reports `applied: false`. No approval row was created on the live workstation. No shadow apply was run.

## Screenshots

- `docs/ui-shots/premium-home-1920x1080.png`
- `docs/ui-shots/premium-home-1280x800.png`
- `docs/ui-shots/premium-intelligence-1280x800.png`
- `docs/ui-shots/premium-markets-1280x800.png`
- `docs/ui-shots/premium-portfolio-1280x800.png`
- `docs/ui-shots/premium-approvals-1280x800.png`
- `docs/ui-shots/premium-agents-1280x800.png`
- `docs/ui-shots/premium-agents-replay-1280x800.png`
- `docs/ui-shots/premium-copilot-1280x800.png`
- `docs/ui-shots/premium-copilot-390x844.png`

## Tests run locally

- `ruff check` and `ruff format --check` on `src` and `tests`
- `mypy src`, including `mypy --platform linux` on the backup module
- `pytest`: full suite passed
- `eslint` on the changed dashboard files with zero warnings
- `tsc --noEmit`
- `npm run build`: `/approvals/respond/[id]` prerenders as a partial page instead of failing outside Suspense
- Playwright `scripts-premium-smoke.mjs` on the production server at 1920x1080, 1440x900, 1280x800, and 390x844: chart canvas, QQQ switch, copilot evidence, idle agent graph, labeled replay, no page errors, no horizontal overflow
- Live GET decide: 405

`npm audit` no longer reports the Playwright high-severity finding after `playwright@1.55.1`. Five high findings remain in the ESLint toolchain (`eslint-config-next` → `@next/eslint-plugin-next` → `fast-glob` → `micromatch` → `braces`). `braces` is overridden to 3.0.3, and `npm audit` still reports that range. `npm audit fix --force` was not used because it would replace the Next.js 16 ESLint config. These packages are not in the production server path.

## GitHub Actions

The link for this push is recorded after the workflow finishes.

## Known limits

- Market data on screen is delayed historical SIP daily bars. There is no real-time stream, and IEX is not mixed into the SIP strategy.
- The stored session is one completed session behind the eligible session until an explicit sync is confirmed.
- News entitlement is unverified.
- Agent motion in the browser check was a replay of a stored run, not a newly generated live review.
- Email links point at localhost and only work on this computer. No tunnel was added.
- Internal shadow grants still do not place Alpaca orders. `ALLOW_ORDER_SUBMISSION` stays false.
