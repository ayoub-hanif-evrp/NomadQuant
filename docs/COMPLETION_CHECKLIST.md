# Completion checklist

Checked items are proved by a test or by a command run on this computer. They are not profit. A matched connectivity fill is not a supervised strategy session.

## Proved by tests or by a command on this computer

- [x] Shadow, daily, and broker ledgers stay separate. The paper book is the internal $100 sleeve.
- [x] Incomplete fill history blocks a new BUY. A disputed journal blocks a strategy SELL. An authorized SELL still runs when the book is unverified rather than disputed.
- [x] Offline lifecycle in `tests/test_project_completion.py`: BUY, partial fill, reconcile, restart, loss stop, protective SELL, kill switch.
- [x] Two operating-system processes claim one prepared row once. `tests/test_process_claim.py`.
- [x] `paper-verify` does not submit or change authorization. After the connectivity journal was written, the 2026-10-24 read returned healthy: SPY position matched, and `nq-connect-spy-buy-5` had one local execution row.
- [x] Raw bars stay raw. Derived series are separate. A split is not applied before its announcement date.
- [x] Qualification can return `FAILED`, `INCONCLUSIVE`, or `RESEARCH_QUALIFIED` only with announcement times. Research fills use the next close. Paper orders are market orders during the session. `comparable_to_paper_fills` is false.
- [x] A missing model is not an AI improvement.
- [x] Browser check `apps/web/scripts/operator-browser.mjs`: desktop and mobile paper page, navigation, the no-order statement, and a visible read failure when the page cannot load status. It passed locally on 2026-10-24.
- [x] `.\scripts\doctor.ps1` passed on this PC, including the API, the dashboard, and a local Ollama response. That is not a from-scratch install.

## Still needs data or a supervised session

- [ ] Announcement timestamps for the 85 SPY and QQQ cash dividends. Alpaca gave `process_date` only. The registered rules stay `NOT_EVALUABLE`.
- [ ] A recorded Ollama session compared with the deterministic book. Ollama answered a health check. No historical model decisions were recorded, and none were invented.
- [ ] A supervised forward paper session. The daily pilot was not authorized. No new order was sent.
- [ ] A from-scratch Windows install on a clean machine. This PC's doctor passed on the existing install.
- [ ] The new browser step in GitHub Actions. It is wired. It has not run on GitHub yet.

## Not required to finish the workstation

- [ ] Splitting `paper_pilot.py` and `apps/web/lib/api.ts`, dependency upgrades, and a screenshot archive.
- [ ] FRED, ALFRED, and EDGAR.

## Release states

- [ ] `ENGINEERING_READY`, `RESEARCH_QUALIFIED`, and `PAPER_VALIDATED` are not granted. See `docs/PROJECT_COMPLETION.md`.
