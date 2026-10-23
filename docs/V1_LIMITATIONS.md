# NomadQuant v1.0 limitations

These are the boundaries recorded for v1 research. They are not a current inventory of the paper path. For that inventory, see [architecture/CAPABILITY_MATRIX.md](architecture/CAPABILITY_MATRIX.md).

## What v1 is

A local program for stored market research, deterministic risk checks, and a supervised internal $100 shadow book. The dashboard is a dark cyan trading terminal. It is not a broker.

## What is not proven

- The SPY 12-1 momentum hypothesis is unchanged. Its parameters were not retuned to the test window.
- A historical backtest is not a forecast and not broker profit.
- Research verification can pass a recomputation and still be `NOT_EVALUABLE` for statistical significance.
- There is no split or dividend point-in-time file. Raw closes are not total returns.
- The forward book has two prospective dry-run `no_trade` cycles and zero fills. That sample is inconclusive.
- A delayed hypothetical daily open is not a real-time executable quote.
- Alpaca paper equity is not the internal $100 allocation.
- v1 had no Alpaca order path. A paper path now exists and is disabled. The filled connectivity buy is not a strategy result. Further paper orders still need a separate authorization.

## Operations

- The forward pilot clock is unset. Starting it requires a `READY_TO_START` preview, `pilot confirm --approval`, and then `worker --mode shadow-apply`. v1.0.1 does not do that for you. Confirmation does not enable unattended scheduled applies.
- Duplicate-prevention is idempotent in memory and in the cycle key. It is not a separate persisted counter.
- Schema version 1 can be stamped onto an older file without deleting rows. There is no earlier migration chain.
- `install-local.ps1` should be run when the API is stopped, because Windows may lock the virtualenv.
- The GitHub repository is public. This release does not change that. If the research records or future notes should stay private, change visibility yourself before pushing anything sensitive. Local databases and `.env` are gitignored.

## Optional later paper adapter

Official Alpaca docs distinguish paper cash, buying power, fractional quantity versus notional, market versus limit, time in force, the asset fractionable flag, partial paper fills, client order id lookup, and timeout ambiguity. A later adapter would stay paper-only, cap risk at the internal $100, require a human confirm, use a stable client order id, and look up unknown timeouts instead of resubmitting. v1 does not implement submit or cancel.
