# Completion checklist

Checked items are proved by a test or by a command run on this computer. They are not profit. A matched connectivity fill is not a supervised strategy session.

## Proved by tests or by a command on this computer

- [x] Shadow, daily, and broker ledgers stay separate. The paper book is the internal $100 sleeve. `paper-verify` reports `sleeve_is_not_broker_cash`.
- [x] Incomplete fill history blocks a new BUY. A disputed journal blocks a strategy SELL. An authorized SELL still runs when the book is unverified rather than disputed.
- [x] Offline lifecycle in `tests/test_project_completion.py`: BUY, partial fill, reconcile, restart, loss stop, protective SELL, kill switch.
- [x] Two operating-system processes claim one prepared row once. A second process cannot claim a row already `unknown`. `tests/test_process_claim.py`.
- [x] `paper-verify` does not submit or change authorization. Missing credentials return `blocked` / `credentials_absent` and do not create a paper database. After the connectivity journal was written, the 2026-10-24 read returned healthy: SPY position matched, and `nq-connect-spy-buy-5` had one local execution row.
- [x] Raw bars stay raw. Derived series are separate. A split is not applied before its announcement date. A price changed after the locked fingerprint stays `NOT_EVALUABLE`.
- [x] Qualification can return `FAILED`, `INCONCLUSIVE`, or `RESEARCH_QUALIFIED` only with announcement times. Research fills use the next close. Paper orders are market orders during the session. `comparable_to_paper_fills` is false.
- [x] A missing model is `NOT_MEASURED`, with prompt version recorded and zero model outputs. It is not an AI improvement.
- [x] Backup and restore round-trip, a bad confirm token, and a corrupt archive are covered by `tests/test_ops_backup.py`. The release run included those tests. It did not restore the live databases.
- [x] `.\scripts\release-check.ps1` passed on 2026-10-24 after the fresh-boot change: Python 3.12, uv, Node v24.21.0, lockfiles, ruff, ruff format, mypy on 150 files, 458 pytest tests, eslint, TypeScript, a production build, the browser check, and `.\scripts\fresh-boot.ps1`. One websockets deprecation warning was printed. The boot did not read `.env`.
- [x] Browser check blocks port 8000 and requires disconnected copy for paper, health, research, market data, and portfolio. Desktop and a 390-pixel paper and portfolio page. It passed locally on 2026-10-24.
- [x] GitHub Actions run 40107872703 on `63fd34b` passed. It predates the `windows-fresh-install` job.

## Still needs data or a supervised session

- [ ] Announcement timestamps for the 85 SPY and QQQ cash dividends. Alpaca gave `process_date` only. The registered rules stay `NOT_EVALUABLE`.
- [ ] A recorded Ollama session compared with the deterministic book. The comparison label stays `NOT_MEASURED`. No historical model decisions were invented.
- [ ] A supervised forward paper session. The daily pilot was not authorized. No new order was sent. The procedure is in `docs/DAILY_PILOT.md`.
- [ ] The `windows-fresh-install` GitHub job. It is written. It has not run.
- [ ] A wiped second Windows computer beyond that runner.

## Not required to finish the workstation

- [ ] Splitting `paper_pilot.py` and `apps/web/lib/api.ts`, dependency upgrades, and a screenshot archive.
- [ ] FRED, ALFRED, and EDGAR.

## Release states

- [x] `ENGINEERING_READY`. The automated release check passed. See `docs/PROJECT_COMPLETION.md`.
- [ ] `RESEARCH_QUALIFIED` and `PAPER_VALIDATED` are not granted.
