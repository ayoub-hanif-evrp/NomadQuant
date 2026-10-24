# Completion checklist

Reviewed against `7a741dc` and the completion pass after it. A checked item is in the repository with a test. It is not a claim of profit or of a live Alpaca session.

## Phase 1 — Integration

- [x] Shadow, daily, and broker ledgers stay separate. The paper book is the $100 sleeve. The shadow book is research. Neither overwrites the other.
- [x] Incomplete fill history blocks a new BUY. A disputed journal blocks a strategy SELL. An authorized SELL still runs when the book is unverified rather than disputed.
- [x] One offline lifecycle: BUY, partial fill, reconcile, restart with no second buy, loss stop, overnight protective SELL, kill switch. `tests/test_project_completion.py`.
- [x] `paper-verify` remains read-only.
- [ ] Simultaneous OS processes, broker outages, and a live partial fill are not demonstrated. The in-process lock covers two threads.

## Phase 2 — Market data

- [x] Raw daily bars stay the stored dataset. `iex` and `sip` stay distinct. `dataset_evidence()` reports `NOT_EVALUABLE` because corporate actions are not stored.
- [ ] Separate split-adjusted and dividend-adjusted datasets. Do not invent them, and do not rewrite the raw experiments.

## Phase 3 — Qualification

- [x] `qualify_daily_strategies` records walk-forward folds, a cash benchmark, and SPY buy-and-hold. The current data returns `NOT_EVALUABLE`. That is not permission to trade.
- [ ] A locked total-return test with costs, regimes, and a multiple-testing adjustment. The present walk-forward is a price-only illustration.

## Phase 4 — AI versus baseline

- [x] A missing model is not counted as a successful veto. The recommendation is `DETERMINISTIC_BASELINE`.
- [ ] A measured comparison against a recorded Ollama session. No live model run is stored.

## Phase 5 — Dashboard

- [x] The paper page shows portfolio truth, execution audit, readiness, and the research-evidence label.
- [ ] Separate validation, audit, and data-quality apps. Playwright is installed as a dependency and is not wired to a trading-desk suite.

## Phase 6 — Release operations

- [x] Existing install, doctor, backup, and CI scripts remain. Linux CI and the Windows reconciliation smoke already pass on `7a741dc`.
- [ ] A fresh Windows install was not rerun in this pass. Browser CI is not wired. Dependency upgrades were not applied.

## Phase 7 — Structure and outside data

- [ ] Split `paper_pilot.py` and `apps/web/lib/api.ts`.
- [ ] FRED/ALFRED and EDGAR adapters. They are optional and are not installed.
- [ ] Screenshot archive. Historical captures stay where they are.

## Phase 8 — Release states

- [x] This checklist and `docs/PROJECT_COMPLETION.md`.
- [ ] `ENGINEERING_READY`, `RESEARCH_QUALIFIED`, and `PAPER_VALIDATED` are not granted. See that document.
