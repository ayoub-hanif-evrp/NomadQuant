# Data quality

Validation runs before a bar is stored. A failing bar rejects that download chunk. The quality report lists problems. It does not insert a replacement candle.

## Bar checks

- Open, high, low, and close are finite and strictly positive.
- Volume is finite and nonnegative.
- Low is less than or equal to open, close, and high. Open and close are less than or equal to high.
- The timestamp is timezone-aware. Its `America/New_York` date is an XNYS session.
- The same symbol and session do not appear twice in one download.
- A returned session lies inside the requested window.
- A sync is bound to one feed. A SIP run refuses an IEX row, and the reverse.

## Calendar checks

The session calendar is `exchange-calendars` XNYS (Apache-2.0). Weekends and NYSE holidays are not sessions. Early-close sessions, such as the day before Independence Day when the exchange closes at 13:00, are real sessions. They are stored and called out in the import warning. Availability stays at 16:30 New York so an early close is not treated as knowable at 13:00.

## Gaps and revisions

After import, the report compares stored session dates with XNYS sessions in the requested window, separately for each symbol and feed. A gap at the start, in the middle, or at the end all count. A continuous block of stored days is not treated as complete when the request was longer than that block. Missing sessions stay missing.

`suitable_for_research` is true only when that requested window is fully present and no conflicting revision is unresolved. A later read through `MarketDataProvider.get_bars` raises if a knowable session in the caller's window is absent. A session withheld because the cutoff is before 16:30 New York is not reported as missing.

A repeated download that changes OHLCV records one revision. Importing that same revised bar again does not add another copy. The original row remains the one readers see, and the revision keeps the timestamp of the download that first observed it. The flag does not mean the series is a total-return index or a verified historical archive.

## What the report cannot prove

- That Alpaca showed this print at 16:30 New York on the session date. `first_retrieved_at` is only the local import time.
- That raw closes include dividends.
- That an IEX bar's volume is the consolidated tape.
- That a float returned by the vendor has full decimal precision.

Run the offline report with:

```powershell
uv run nomadquant-data report
```
