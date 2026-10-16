# Hypothesis: SPY long-only time-series momentum (price-only)

**Hypothesis ID:** `H-SPY-TSMOM-2012-adapted`  
**Experiment ID:** `spy-tsmom-v1`  
**Status:** Pre-registered configuration. Not a claim of profit.

## Statement

On SPY, a pre-specified long-only time-series momentum rule, adapted from Moskowitz, Ooi & Pedersen (2012), may offer improved downside-risk characteristics relative to passive SPY exposure over selected historical regimes, after realistic execution costs.

The original paper studied a broad futures universe. This experiment tests a single US ETF with $100 virtual capital, no leverage, and no shorts.

## Citations

1. Moskowitz, Tobias J., Yao Hua Ooi, and Lasse Heje Pedersen. 2012. "Time Series Momentum." *Journal of Financial Economics* 104 (2): 228–250. https://doi.org/10.1016/j.jfineco.2011.11.003
2. White, Halbert. 2000. "A Reality Check for Data Snooping." *Econometrica* 68 (5): 1097–1126. https://doi.org/10.1111/1468-0262.00152
3. Bailey, David H., and Marcos López de Prado. 2014. "The Deflated Sharpe Ratio." *Journal of Portfolio Management* 40 (5): 94–107. https://doi.org/10.3905/jpm.2014.40.5.094

## Signal and timing

- Universe: SPY only
- Feed: SIP raw daily bars
- Research mode: **price-only** (dividends excluded)
- Lookback: 252 sessions
- Skip: 21 sessions (recent month omitted from the return)
- Momentum = close[t − skip] / close[t − skip − lookback] − 1
- That is 252 return intervals, not the shorter close[t − 21] / close[t − 252] − 1 reading
- Warm-up is lookback + skip + 1 sessions (274). Fewer sessions is INSUFFICIENT_DATA, not a cash signal
- Target weight = 1 if momentum > 0 else 0 (cash)
- Rebalance: first NYSE session of each calendar month
- Information cutoff: modeled availability of session t’s close (16:30 America/New_York)
- Execution: next session **open** after the signal session. Same-day close fills are forbidden.

## Costs

Commission $0, spread 1 bps, slippage 1 bps, minimum notional $1, fractional shares to 6 decimals, initial capital $100.

Execution convention `half_spread_plus_full_slippage_v1`: the buy price is mid + half the spread + the full slippage basis point. Commission, when nonzero, is a separate cash item. Spread and slippage are not deducted a second time. The older shadow formula `(spread_bps + slippage_bps) / 20000` is not used for new fills and is not written back into stored runs.

## Windows

Warm-up uses data from 2018-01-02. Evaluation begins 2019-02-01.

| Window | Start | End | Purpose |
| --- | --- | --- | --- |
| Train | 2019-02-01 | 2021-12-31 | Documented sample regime only. No parameter fitting. |
| Validation | 2022-01-01 | 2023-12-29 | Documented sample regime only. |
| Locked test | 2024-01-02 | 2026-10-14 | Held for reporting. Not used to tune parameters. |

## Benchmarks

1. SPY buy-and-hold (enter at first evaluation open)
2. Cash-only
3. Simple baseline: 6-month TSMOM (126 sessions, skip 0), same costs and timing

## Caveats

- Not a total-return study
- Not paper trading and not a broker order
- Sharpe/Sortino are descriptive; no significance claim
- One pre-registered configuration; trial history still recorded for every run
