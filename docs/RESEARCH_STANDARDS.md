# Research standards

These rules apply to every strategy NomadQuant evaluates. Phase 1 does not implement a strategy and does not report a result. A backtest, a paper fill, and a live fill are different claims. This document forbids treating them as the same claim.

Published papers are inputs to a hypothesis. They are not permission to trade, and they do not transfer automatically to a $100 long-only portfolio of US ETFs. The studies below use different universes, horizons, costs, and sample sizes. A result on liquid futures or a broad cross-section of stocks can disappear once the universe is a handful of ETFs, the capital is $100, and turnover has to pay spreads.

## Initial references

1. Moskowitz, Tobias J., Yao Hua Ooi, and Lasse Heje Pedersen. 2012. "Time Series Momentum." *Journal of Financial Economics* 104 (2): 228–250. https://doi.org/10.1016/j.jfineco.2011.11.003

   The paper studies time-series momentum across equity index, currency, commodity, and bond futures. That is not a $100 long-only US ETF book. Any ETF test inspired by it needs its own hypothesis, costs, and out-of-sample window.

2. Gu, Shihao, Bryan Kelly, and Dacheng Xiu. 2020. "Empirical Asset Pricing via Machine Learning." *The Review of Financial Studies* 33 (5): 2223–2273. https://doi.org/10.1093/rfs/hhaa009

   The paper compares machine-learning models on a large US equity cross-section. It is a reason to measure a model against simpler benchmarks, not a reason to deploy a neural net on a four-ETF portfolio.

3. Bailey, David H., and Marcos López de Prado. 2014. "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality." *The Journal of Portfolio Management* 40 (5): 94–107. https://doi.org/10.3905/jpm.2014.40.5.094

   Trying many configurations and reporting the best Sharpe inflates the result. NomadQuant has to keep the trial record, not only the winner.

## Mandatory requirements

1. **Hypothesis first.** Write a falsifiable statement before looking at a performance number. Cite the primary paper or dataset documentation the idea comes from. "It backtested well" is not a hypothesis.

2. **Record the experiment.** Store the universe, data source, vendor, symbol list, timestamp convention, timezone, corporate-action policy, assumptions, code revision, and full configuration. Another person must be able to rerun it.

3. **No future information.** Prevent look-ahead bias, leakage from later revisions, survivorship bias, and accidental use of data that was not knowable at the decision time. Point-in-time identifiers and an `as_of` cutoff are required once historical data exists. Delisted names stay in the universe for the period they were actually tradable.

4. **Time order.** Split train, validation, and test chronologically. Never randomly shuffle a financial time series. Do not fit preprocessing on the full sample and then split.

5. **Walk-forward.** Where a model or rule has estimated parameters, evaluate it walk-forward on data after each fit. A single in-sample curve is not an evaluation.

6. **Costs.** Include commissions when they apply, a bid-ask spread assumption, slippage, and turnover. A $100 account makes fixed commissions and wide spreads material. State the assumption even when the assumed cost is zero, and say why.

7. **Benchmarks.** Compare against buy-and-hold SPY, a cash benchmark, and a simple baseline that matches the hypothesis (for example, equal weight or monthly momentum) before comparing against a more complicated model.

8. **Measures.** Report net return, maximum drawdown, volatility, Sharpe ratio, turnover, gross and net exposure, and trading costs. Report the sample length. Do not report a Sharpe from a handful of trades as if it were stable.

9. **Trial registry.** Keep every configuration that was run, including the ones that failed. Selecting the best after the fact is a result that needs the deflated-Sharpe style of skepticism in Bailey and López de Prado, not a promotion.

10. **Paper forward test.** A strategy cannot be promoted on a backtest alone. It needs a paper forward test that uses the same code path intended for later execution, with the same risk limits. Promotion is a later phase. It is not available now.

11. **Label results honestly.** Backtest output is a backtest. Paper fills are paper fills. Neither is realized profit. User interfaces and reports must use those words.

12. **Justify complexity.** Any machine-learning or LLM addition must beat the simpler non-LLM baseline from requirement 7 on the locked test window. If it does not, keep the simpler rule. An LLM never overrides a risk rejection and never submits an order.

## Capital constraint

The $100 virtual capital is a constraint on what is worth testing. It is not a profitability target. A strategy that needs leverage, shorting, options, or high turnover to look acceptable does not fit the risk principles in [ROADMAP.md](ROADMAP.md).

## What this phase claims

Nothing about returns. The standards exist so later work has a bar before the first experiment is run.
