# Paper Execution Readiness

**Status:** Shadow-only. No Alpaca paper or live order submission is authorized.  
**Capital:** Internal virtual capital is exactly **$100**. This is not Alpaca paper equity.  
**Locks:** `TRADING_MODE=paper`, `ALLOW_ORDER_SUBMISSION=false`, `API_HOST=127.0.0.1`.

## Prompt 12 verification matrix

| Guarantee | Verified? | Notes |
|-----------|-----------|-------|
| Pending month-start resumes without `--signal-session` | Yes | `test_pending_month_start_resumes_on_next_cycle_without_override` |
| GET never mutates ledger/reservations | Yes | `test_shadow_get_endpoints_do_not_mutate_ledger` |
| Outbox after shadow commit only | Yes | Risk projection via `shadow_outbox` + `deliver_outbox` |
| Policy-aware partial sizing | Yes | Caps to `max_single_transaction_usd` without limit bypass |
| Momentum None → INSUFFICIENT_DATA | Yes | Fail-closed, not silent cash signal |
| Timeline filter totals in SQL | Yes | `count_cycles(status=…)` |
| Calendar coverage ≠ row count | Yes | `market_data_status` warm-up window |
| Explicit recover CLI | Yes | `nomadquant-shadow recover` |
| Worker inspect/dry-run/shadow-apply | Yes | Default schedule = inspect |
| Zero Alpaca orders | Yes | No order routes; gateway dry-run only |
| Worker hard gate on BLOCKED / failed reconcile | Yes | Prompt 13: no cycle when preflight blocked |
| Explicit recovery only | Yes | Apply no longer auto-calls recover_interrupted |

## Current verified guarantees

- Shadow portfolio equity is computed in the backend as `cash + Σ(quantity × validated mark)`.
- Missing marks yield `valuation_unavailable` (no invented equity).
- Forward and retrospective ledgers are physically separate SQLite databases.
- Ledger mutations use optimistic concurrency (`WHERE version = expected`).
- Reservations, fills, cash, holdings, and cycle records are authoritative in the shadow DB.
- Risk-store writes are derived/outbox-style — **not** cross-database atomic.
- Crash recovery releases interrupted active reservations exactly once (`nomadquant-shadow recover`; not on GET preflight/reconcile/ops).
- Pending intents resume chronologically before new signals.
- Daily worker (`nomadquant-shadow worker`) supports inspect / dry-run / shadow-apply with structured statuses and outcome JSON under `data/shadow_logs/`.
- Duplicate `cycle_key` apply is idempotent (no double fill).
- `APPROVE` is not an execution; dry-run never mutates the ledger.
- API POST is an explicit localhost allowlist. There are still no order routes.
- Forward `--signal-session` overrides older than five days are blocked as chronology violations.

## Remaining risks

- Daily OHLC opens support **delayed observation simulation** only — not proven real-time open fills.
- SIP historical entitlement may be incomplete; IEX must never be silently mixed.
- Risk engine and shadow sizing assumptions can diverge from broker fractional-share rules.
- Outbox projection to `risk.sqlite` can lag after a crash (shadow ledger remains source of truth).
- No live market-hours tick feed; holiday/early-close handling depends on the NYSE calendar module.

## Exact risk-policy assumptions

- Long-only, no leverage/margin, no shorts/options.
- Internal capital $100; max exposure and cash rules from `RiskPolicy` defaults.
- Proposal `as_of` uses the **observation timestamp**, not signal-bar availability.

## Reconciliation design

- `nomadquant-shadow reconcile` checks: non-negative cash, reserved ≤ cash, long-only holdings, equity = cash + marked holdings when marks exist.
- Equity history points are written only from persisted cycle outcomes.

## Idempotency design

- Stable `cycle_key = {label}:{feed}:{symbol}:{signal_session}:{strategy_id}`.
- Intent IDs are deterministic from `cycle_key`.
- Reservation release and recovery are status-gated (`active` → `released`/`committed` once).

## Broker fractional-share / order-type confirmation still needed

Before any Alpaca paper milestone:

- Confirm fractional share precision and rounding for SPY.
- Confirm supported order types for paper gateway (market vs limit at open).
- Confirm notional vs qty submission rules and reject handling.
- Confirm buying-power semantics vs our reserved-cash model.

## Market-hours behavior

- Signal eligibility uses completed daily bars and the 16:30 America/New_York availability model.
- That model does **not** prove next-session open availability at signal time.
- Preflight returns `WAITING_FOR_DATA` / `NO_REBALANCE_DUE` / `ALREADY_PROCESSED` rather than forcing success.
- Scheduled runs default to **inspect**; **shadow-apply** is opt-in and still shadow-only (see `docs/SHADOW_SCHEDULING.md`).

## Stale-data safeguards

- Valuation refuses missing marks.
- Preflight checks warm-up window, feed coverage, and stuck reservations.
- Feed changes require a new strategy/config version (no silent SIP↔IEX mix).

## Emergency-stop semantics

- `ALLOW_ORDER_SUBMISSION=false` is validated at settings load.
- Preflight `BLOCKED` if paper locks fail.
- Shadow apply never calls a broker client.

## Failure and recovery handling

1. Reserve in shadow DB.  
2. Simulate fill + OCC ledger update in the same DB transaction as the cycle row.  
3. On OCC conflict: release reservation / recover; do not lose cash silently.  
4. Risk audit projection is best-effort after commit.

## Planned manual authorization flow (future)

1. Separate explicit written authorization for Alpaca **paper** only.  
2. Fresh code review of gateway + policy hash pin.  
3. Dry-run parity report vs shadow fills.  
4. Manual single-order submit with human confirmation.  
5. Reconciliation against Alpaca paper account (still ≠ $100 internal book).

## Prompt 14 local evidence (2026-10-16, this workstation)

These are observed results, not a completed forward fill.

| Check | Result |
|-------|--------|
| Feed | SIP only. `has_symbol(SPY, iex)` is false. No automatic SIP→IEX switch. |
| Coverage before sync | SPY and QQQ each had 2208 sessions through 2026-10-14. Missing completed session: 2026-10-15. |
| `data-sync --feed sip` | `success`. Inserted 2 rows (SPY and QQQ for 2026-10-15). Unchanged 554. Conflicts 0. Early-close notes for 2025-11-28 and 2025-12-24. |
| Coverage after sync | 2209 sessions each. Latest stored 2026-10-15. Warm-up complete for the requested window 2025-09-09..2026-10-15. |
| Retrieval provenance | SPY 2026-10-15 open 766.25 close 771.79, `first_retrieved_at` 2026-10-16T11:00:59Z. QQQ open 718.55 close 728, same retrieval timestamp. Modeled availability remains 2026-10-15T20:30:00Z. This is when the computer stored the daily bar, not a real-time open quote. |
| Preflight | `NO_REBALANCE_DUE`. Cash 100, ledger version 1, no reservations. Fill session 2026-10-16 open is missing because that session is not finished. |
| Reconcile before processing | `ok=true`. Equity 100. |
| Worker inspect | run `19aee933970d44658a98287822c905a3`, status `WAITING_FOR_SESSION`. No cycle. |
| Worker dry-run | run `533f7970f2af44efbef94c2587a7d328`, status `COMPLETED_NO_TRADE`. Ledger stayed version 1, cash 100, holdings empty, reserved 0. |
| Pending / outbox | 0 pending intents, outbox backlog 0. |
| Shadow-apply | Not run. |
| Task Scheduler install | Not run. |
| Alpaca orders | None. Sync used the historical bars client only. |
| Ollama | Models are installed locally. `ollama ps` showed no running model. Daily worker did not call Ollama. |
| Real-time executable evidence | No. The new bars are delayed daily OHLC. |

## Prompt 15 local evidence (2026-10-16, this workstation)

These are observed results. They are not a completed forward fill and not a confirmation of the pre-registered momentum hypothesis.

| Check | Result |
|-------|--------|
| SIP coverage | SPY and QQQ each have 2209 sessions. Latest stored session 2026-10-15. Warm-up window 2025-09-09 through 2026-10-15 is complete (`missing_count=0`). 2026-10-16 was not a completed session at inspection time. |
| Incremental sync | A missing-data sync on this coverage is a noop: `provider_requests=0`. The same warm-up window is 278 sessions, 556 symbol-rows. The previous live sync fetched 556 rows to insert 2. A revision audit still re-fetches that window and was not run. The regression test deletes one stored SPY session and expects one SPY-only provider call, with QQQ omitted. |
| Missed month-start | Live ledger has no `missed_signal` row. The pilot clock is unset because `shadow-apply` was not run, so earlier months are not backfilled as operational misses. Tests cover a shutdown on the first session of February 2020, a two-day outage, a weekend month change, a pending intent that resumes, duplicate detection, and first contact that does not invent a historical fill. |
| Preflight / reconcile | `NO_REBALANCE_DUE`. Reconcile `ok=true`. Cash 100, reserved 0, holdings empty, ledger version 1. |
| Worker inspect | run `70ab4b4348c54f6cbb0335fa2339960f`, `WAITING_FOR_SESSION`. No new cycle. |
| Worker dry-run | run `6a1a56b949254bea95aad5f2736124bb`, `COMPLETED_NO_TRADE`. Reused cycle 2 for 2026-10-15. Ledger stayed version 1. |
| Daily inspect | operation `4c54213e5b334bf0a3b3469a844c7768`, `COMPLETED`. Sync skipped. |
| Daily dry-run | operation `08637b32e4c74626b9614bff26ec30fe`, `COMPLETED`. Sync skipped. Worker run `2de7126b00f04df4aca07adfa3a5e25c`. |
| Prospective records | 2 dry-run `no_trade` cycles (2026-10-14 and 2026-10-15). Creation timestamps were left unchanged. |
| Hypothetical fills | 0. Fill model remains `delayed_hypothetical_daily_open` and is `NOT_EVALUABLE` until a fill exists. |
| Independent verify | Cycles 1 and 2 both `PASS`. Evidence hash, momentum, bar hash, future-bar exclusion, retrieval cutoff, and unchanged cash recomputed. A tampered hash fails in tests. |
| Baseline | Inconclusive. Cash baseline stays 100. No SPY buy-and-hold comparison is claimed against shadow fills, because there are no fills. Raw closes are not total returns. |
| Shadow-apply | Not run. |
| Task Scheduler install | Not run. |
| Alpaca orders | None. No data-sync and no order client were invoked. |
| Ollama | One review of research run 2 with installed `qwen3.5:9b`. Agent run 5 succeeded in 68s (11:49:10Z to 11:50:18Z). Researcher, skeptic, and reviewer stages completed. Deterministic verification overrode the model: 5 numerical claims did not match stored test-window metrics. Verdict `verification_failed`. Not a trading decision and not a broker order. No new model was downloaded. Memory was not sampled. |

## Prompt 16 local evidence (2026-10-16)

| Check | Result |
|-------|--------|
| Fill convention | `half_spread_plus_full_slippage_v1`. At a $100 mid, 1 bp spread and 1 bp slippage, buy is $100.015 and sell is $99.985. The old shadow formula produced $100.01 and is not used for new fills. Stored cycles were not rewritten. |
| Ledger | Cash 100, reserved 0, holdings empty, version 1. Reconcile `ok=true`. |
| SIP | SPY and QQQ each have 2209 sessions through 2026-10-15. Missing count 0. |
| Cycle 2 | Independent verifier `full_cycle=PASS`. Fill assumption is `NOT_APPLICABLE` because the row is a dry-run `no_trade`. |
| Research audit | Run 2, 5 of 93 decisions. Signal, prefix, cost, and unsafe-price checks passed. Status `NOT_EVALUABLE` because split and dividend files are absent. Not comprehensive. |
| Worker dry-run | `ece6425b9ab642959bfc472bc8f5b175`, `COMPLETED_NO_TRADE`. Cash stayed 100. |
| Shadow-apply / Alpaca orders / paper reset | Not run. |

## Go / no-go checklist

| Item | Go? |
|------|-----|
| Shadow equity valuation correct | Yes (backend) |
| Forward ≠ retrospective ledger | Yes |
| OCC + reservation recovery | Yes |
| No broker order paths in API | Yes |
| Real-time open provenance | **No** — stored daily bars record `first_retrieved_at`; fills stay `delayed_hypothetical_daily_open` |
| Alpaca fractional confirmation | **No** |
| Explicit paper-order authorization | **No** |
| Autonomous execution | **Forbidden** |

**No-go for Alpaca paper orders until the remaining rows are closed under a new authorized prompt.**

## Prompt 18 workstation evidence (2026-10-16, about 17:51 UTC)

| Check | Result |
|-------|--------|
| Version | `1.0.0-rc.1` candidate for the local research and shadow scope only. |
| SIP | SPY and QQQ each have 2209 sessions. Latest stored and latest safe session `2026-10-15`. Missing 0 in the warm-up window `2025-09-09` through `2026-10-15`. `2026-10-16` open was not stored. Last successful historical store `2026-10-16T11:00:59Z`. |
| Entitlement | Historical SIP bars are stored. This run did not query account buying power or the asset fractionable flag. |
| Ledger | Cash 100, reserved 0, holdings empty, realized 0, version 1. Reconcile `ok=true`. |
| Cycles | 2 prospective dry-run `no_trade` rows. 0 fills. 0 pending intents. 0 unresolved reservations. |
| Verification | Recent sample 2 of 2 passed. That sample is not a full-history execution proof, and `no_trade` fill checks stay `NOT_APPLICABLE`. |
| Pilot | `WAITING_FOR_SESSION`. Clock unset. Worker script present. `pilot_running` false. Not ready to start a fill today because no month-start rebalance is due and the next open is missing. |
| Daily inspect | `COMPLETED`, worker `WAITING_FOR_SESSION`. Cash stayed 100, version stayed 1. |
| Daily dry-run | `COMPLETED`, worker `COMPLETED_NO_TRADE`. Reused the existing cycle. Cash stayed 100, version stayed 1. |
| Shadow-apply | Not run. |
| Alpaca orders | None. |
| Ollama | Offline claim benchmark covers five fixed cases and calls no model. A new two-model live review was not run in this pass. |

## Pilot preview and confirmation

`nomadquant-shadow pilot preview` prints capital, holdings, snapshot version, policy hash, data readiness, pending intents, the next signal context, the delayed-hypothetical model, the local files a later apply would touch, the recovery command, and that a committed fill cannot be undone. It sets `mutates_forward_ledger` false.

`nomadquant-shadow pilot confirm --approval HASH` accepts the token only when it equals the hash of the current preview. A mismatch, including any relevant state change, returns `REJECTED` and exit 1. Acceptance prints the worker command and still does not apply.

## Pilot state transitions

| State | When it is used |
| --- | --- |
| `NOT_CONFIGURED` | The forward ledger file is absent. |
| `RECOVERY_REQUIRED` | An interrupted reservation is still active. |
| `BLOCKED` | Preflight is blocked, the guard refuses application, or reconcile failed. |
| `WAITING_FOR_DATA` | Required market coverage is incomplete. |
| `FAILED` | A recorded daily operation failed. |
| `PENDING_OBSERVATION` | A pending intent exists but its fill bar is not stored, or a rebalance is scheduled without the next open. |
| `OBSERVING` | The pilot clock has been set. This does not mean a worker process is alive. |
| `READY_TO_START` | A month-start rebalance is scheduled, the next observation is stored, and the clock has not started. |
| `WAITING_FOR_SESSION` | Data is complete and no rebalance is scheduled. |

A pending row is not executable by itself. `pilot_running` is true only while `data/shadow_worker.lock` is younger than two hours.

## Future Alpaca paper-order milestone (not enabled)

This sprint does **not** turn on broker submission. `ALLOW_ORDER_SUBMISSION` stays false. Agents still have no order tools.

## Prompt 19 workstation evidence (2026-10-17, this PC)

Observed on Saturday 17 October 2026. This is not a completed forward fill and not Alpaca trading.

| Check | Result |
|-------|--------|
| Doctor | PASS: Python 3.12, uv, Node v24.21.0, `.env` present, web build present, data files present, API `:8000`, dashboard `:3000`, Ollama tags endpoint responded. |
| SIP coverage | SPY and QQQ each 2210 sessions through **2026-10-16**. Missing 0. Warm-up complete. The earlier note that bars stopped at 2026-10-15 is stale. |
| IEX snapshot | Last trade **$763.31**, Friday 16 Oct 4:47 PM New York, labeled **Last IEX trade (market closed)**. Not used by the strategy. |
| Market clock | Saturday. Regular session closed until Mon 19 Oct 9:30 New York. |
| Preflight | `NO_REBALANCE_DUE`. Cash 100, version 1, no reservations. Next strategy signal 2026-11-02, hypothetical fill 2026-11-03. |
| Reconcile | `ok=true`. Equity 100. Holdings empty. |
| Pilot | `WAITING_FOR_SESSION`, lifecycle **UNARMED**, **armable=true**. Clock unset. 0 pending intents. 0 hypothetical fills. |
| Daily inspect | `COMPLETED`, worker `WAITING_FOR_SESSION`. Ledger unchanged. |
| Daily dry-run | `COMPLETED_NO_TRADE`. Wrote prospective cycle 3 for 2026-10-16 (`no_trade`, not month-start). Cash stayed 100, version 1. |
| Shadow-apply / schedule / Alpaca orders | **Not run.** `ALLOW_ORDER_SUBMISSION=false`. |
| Isolated BUY/HOLD/SELL | Passed in a temporary database (`tests/test_shadow_lifecycle_parity.py`). Not the live $100 book. |
| Month-start arm | Passed with fixtures (`tests/test_pilot_month_start_lifecycle.py`). Live clock remains unset. |
| Ollama | `qwen3.5:9b` installed. `ollama ps` was empty before the review. No model was downloaded. |
| Live web review | Button started **run 6** of research run 2 with `qwen3.5:9b`. Researcher 63.7s (`read_run_card`), Skeptic 21.0s (`read_run_card`), Reviewer 10.4s (`verify_backtest`), Verifier 0ms. Status succeeded. Verdict **verification_failed** because invented numbers did not match stored test-window metrics, and independent replay was FAIL. Browser showed LIVE working, then recorded run 6 with Verifier **Flagged**. |
| Copilot | `qwen3.5:9b` answered why there are no trades from stored evidence: Saturday, monthly schedule, pilot not started, next fill 2026-11-03. Desktop and mobile screenshots captured. |
| News analysis | Sequential three-stage pipeline is implemented and fixture-tested. Live Scout was not sent; no headlines were on the workstation, so Analyze was not clicked. |
| Email approval | Inbox empty, which is correct: no eligible BUY/SELL proposal exists. Localhost-only links are documented on the page. |
| `verify-all.ps1` | ALL CHECKS PASSED after updating route safety to the POST allowlist. No order routes. |
| Paper orders | Still disabled. Future milestone remains the ten-point plan above. |

**No genuine fill occurred. Zero trades is the expected Saturday state, not proof that execution works.**

When a later written authorization is given, paper orders should be a separate gateway that:

1. Uses the Alpaca **paper** API only (`https://paper-api.alpaca.markets`). Live trading remains forbidden.
2. Requires a second explicit execution flag, distinct from shadow-apply and email approval.
3. Confirms the paper account, `SPY` as a fractionable equity, and the $100 internal notional cap before any submit.
4. Submits only after the same risk recheck that currently gates the internal ledger fill.
5. Uses a stable unique `client_order_id` per approved proposal and never retries while the broker outcome is unknown.
6. Reconciles `GET /v2/orders:by_client_order_id` and `GET /v2/orders/{order_id}` before any second submit.
7. Handles rejection, partial fill, and after-hours queued orders without inventing a fill in the $100 book.
8. Reconciles broker positions independently of the internal ledger.
9. Provides an emergency halt that stops new submits without deleting history.
10. Keeps Researcher, Skeptic, Reviewer, News Scout, and Copilot off the order path.

Email approval in this sprint still authorizes **only** the internal shadow transaction. It is not a broker ticket.
