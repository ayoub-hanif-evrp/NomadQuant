# Market data

NomadQuant stores daily bars for a small US ETF universe, starting with SPY and QQQ. The bars come from Alpaca's market-data API at `https://data.alpaca.markets`. That host is separate from the paper trading host. The trading client remains paper-only, and this pipeline does not submit orders.

The local file is `data/market.sqlite` unless `MARKET_DATA_PATH` is set. It is not the operational event database, and it is gitignored. Nothing is downloaded during installation or API startup.

## What is stored

Each observation records:

- Symbol and US session date (`America/New_York`)
- Provider bar timestamp in UTC
- Open, high, low, close, and volume, stored as decimal text
- Provider `alpaca`, feed `sip` or `iex`, adjustment `raw`, timeframe `1Day`, currency `USD`
- `first_retrieved_at`: when this import run first stored the row
- `available_at`: modeled availability, 16:30 America/New_York on that session
- SHA-256 of the observation fields

Prices that are missing, non-numeric, or not strictly positive are rejected. Volume may be zero only when the vendor actually reports zero. Rows are not invented to fill a chart.

Alpaca's SDK returns OHLC as binary floating point. NomadQuant converts that text form into `Decimal`. The conversion cannot recover precision the float already lost. A later vendor that returns decimal strings can be stored without that step.

## Feeds

The canonical research feed is consolidated SIP when the account can read it. Alpaca documents that historical SIP can be queried without the paid subscription outside a recent restricted window. The sync command therefore stops at the latest completed session, which is older than that window once 16:30 New York has passed.

If SIP returns an authorization failure, the command stops and tells you to rerun with `--feed iex`. It does not switch feeds by itself. IEX rows and SIP rows can both exist in the database, but a read is bound to one feed. IEX is one exchange's trades, not consolidated US volume. Do not treat an IEX series as the same sample as SIP.

## Adjustment

The stored policy is `raw` (unadjusted). Raw prices are not a dividend-adjusted total-return series. A long-horizon return that ignores dividends, or that ignores a split, is not a valid performance series. Split and dividend adjustments have to be an explicit later dataset, with their own policy value. This store does not silently rewrite raw rows into adjusted rows.

## Time and availability

US sessions come from the `exchange-calendars` XNYS calendar. A weekday is not automatically a session. Holidays are rejected. Early closes are stored and reported; their modeled availability is still 16:30 New York, which is later than a 13:00 close.

Daily timestamps from Alpaca are the start of the New York session, expressed in UTC (04:00 during EDT, 05:00 during EST). The session date is that timestamp converted to `America/New_York`, including daylight-saving transitions. The session date is not the time a strategy may use the close.

Modeled availability is 16:30 America/New_York on the session date, stored in UTC. A request whose cutoff is the same morning, including the 09:30 open, does not receive that day's close. `StockBarsRequest.asof` is Alpaca's symbol-mapping parameter. NomadQuant does not use it as an information cutoff.

`available_at` is a model. `first_retrieved_at` is the time this computer stored the row. A download performed today does not prove which revision was visible on the historical afternoon. This database is not a verified point-in-time archive.

## Revisions

The unique key is symbol, session date, feed, timeframe, adjustment, and provider. Repeating an import leaves an identical row in place. A later download with different OHLCV is appended to `bar_revisions` and does not replace the original. Import runs record start and finish, symbols, feed, row counts, warnings, and an error code.

A failed chunk is not written. Chunks that already committed stay. Network and rate-limit errors are retried with bounded exponential backoff. Authorization failures are not retried.

## Commands

From the repository root in PowerShell, after `uv sync --all-groups` and a paper key pair in `.env`:

```powershell
uv run nomadquant-data sync --symbols SPY,QQQ --start 2018-01-01 --feed sip
uv run nomadquant-data report
```

`--feed` defaults to `sip` and the command prints that choice. Omit `--end` to use the latest NYSE session whose modeled availability is already at or before the current time. An explicit end on a weekend, a holiday, or a session that has not reached 16:30 New York is rejected before any request.

If SIP is not entitled:

```powershell
uv run nomadquant-data sync --symbols SPY,QQQ --start 2018-01-01 --feed iex
```

Keep that IEX file separate from any SIP sample. The command prints counts, the date range, gaps, and warnings. It does not print credentials. A genuine failure exits nonzero. Running it again does not duplicate unchanged rows.

`GET /api/market-data/status` reads the local file and does not download. The dashboard page Market Data shows the same summary. It does not draw a price chart.

## What this dataset can support

It can support inspection of raw daily SPY and QQQ levels from one named feed, with a documented availability model and a record of later conflicting downloads.

It cannot support a claim of dividend-adjusted total return, a claim that a historical strategy would have seen these exact prints at 16:30 New York, or a claim that IEX volume is consolidated market volume. Those require a different dataset and a different statement of assumptions.
