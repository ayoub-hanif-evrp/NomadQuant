# Changelog

## 1.0.1

Maintenance release.

- A forward shadow-apply now requires a stored one-time approval bound to the ledger version, policy hash, feed, and market fingerprint. The approval expires, is consumed once, and is not a broker authorization. Waiting, failed, and blocked states cannot be approved. A separate schedule flag is not turned on by confirmation.
- Backups include the retrospective ledger, worker logs, agent memos, and a schema catalog. Restore uses allowlisted names, rejects path escapes, and rolls back from a safety copy. The confirm token is a checksum, not a signature. Each database is snapshotted on its own; this is not one atomic whole-system snapshot.
- Dashboard reads open the shadow ledger read-only and do not create or migrate it.
- Stop refuses a tracked PID whose start time does not match, so a reused Windows PID is not killed.

## 1.0.0

Local research and supervised shadow workstation.

- Verifier exit codes, independent quote timestamps, and explicit pilot states from the release candidate.
- Windows scripts to install, start, stop, diagnose, back up, and restore.
- SQLite online backup with a manifest, checksums, and a confirm token. `.env` is excluded.
- Schema version 1 can be added to an older database without deleting rows.
- Command Center shows Ollama readiness, shadow equity, and links to the next page.
- Research runs open from a stable `?run=` id.
- No broker order submission.

## 1.0.0-rc.1

Correctness release candidate: verifier contract, retrieval-time checks, full-history shadow counts, pilot preview, and an offline claim benchmark.
