# Release blockers

v1.0 ships with the limits in [V1_LIMITATIONS.md](V1_LIMITATIONS.md). The items below are accepted product boundaries, not open order-path defects. This is not authorization to submit broker orders.

Ranked remaining issues, observed on this workstation on 2026-10-16:

1. **The forward pilot is not running.** `pilot status` is `WAITING_FOR_SESSION`. The pilot clock is unset, `pilot_running` is false, and no month-start rebalance is due. `2026-10-16` has no stored open because that session was still open at inspection (about 13:51 America/New_York). Do not start it without an explicit preview hash and a separate `worker --mode shadow-apply`.
2. **There are no forward fills.** The ledger is cash 100, reserved 0, holdings empty, version 1. Two prospective dry-run `no_trade` cycles exist (2026-10-14 and 2026-10-15). A verifier PASS on those rows is not verified execution economics. The performance sample is inconclusive.
3. **Daily bars are not real-time executable quotes.** SIP coverage is 2209 sessions each for SPY and QQQ through 2026-10-15, missing 0 in the warm-up window. Fills, if later applied, stay `delayed_hypothetical_daily_open`.
4. **Research audit remains NOT_EVALUABLE** without a split and dividend point-in-time file. Raw closes are not total returns. The pre-registered hypothesis is unchanged and is not confirmed by the forward sample.
5. **Broker capability is documentary.** Profile `alpaca-readonly-2026-10-16-rc1` does not query the paper account or the SPY fractionable flag. No order-submission API is implemented. Paper cash and buying power are not the internal $100 book.
6. **Duplicate-prevention events are not a persisted counter.** A repeated apply returns the existing cycle in memory. Full-history SQL counts fills, misses, rejections, and daily operations. Verification pass/fail numbers are a recent sample.

Not blockers for this release candidate: chart libraries, new strategies, new models, cloud deployment, and an Alpaca order gateway.
