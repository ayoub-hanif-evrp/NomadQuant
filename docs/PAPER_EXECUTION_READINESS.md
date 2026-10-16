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
- API remains GET-only with no order routes.
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

## Go / no-go checklist

| Item | Go? |
|------|-----|
| Shadow equity valuation correct | Yes (backend) |
| Forward ≠ retrospective ledger | Yes |
| OCC + reservation recovery | Yes |
| No broker order paths in API | Yes |
| Real-time open provenance | **No** |
| Alpaca fractional confirmation | **No** |
| Explicit paper-order authorization | **No** |
| Autonomous execution | **Forbidden** |

**No-go for Alpaca paper orders until the remaining rows are closed under a new authorized prompt.**
