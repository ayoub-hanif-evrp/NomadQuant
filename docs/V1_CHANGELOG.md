# Changelog

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
