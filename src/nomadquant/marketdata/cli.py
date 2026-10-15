"""Local commands for daily-bar sync and the offline quality report."""

import argparse
import sys
from datetime import UTC, date, datetime

from nomadquant.config import Settings, get_settings
from nomadquant.marketdata.alpaca_bars import AlpacaDailyBars
from nomadquant.marketdata.availability import latest_safe_session
from nomadquant.marketdata.errors import MarketDataError
from nomadquant.marketdata.report import market_data_status
from nomadquant.marketdata.store import MarketStore
from nomadquant.marketdata.sync import sync_daily_bars


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="nomadquant-data")
    sub = parser.add_subparsers(dest="command", required=True)
    sync = sub.add_parser("sync", help="Download completed daily bars for one feed.")
    sync.add_argument("--symbols", default="SPY,QQQ")
    sync.add_argument("--start", required=True)
    sync.add_argument("--end", default=None)
    sync.add_argument("--feed", choices=["sip", "iex"], default="sip")
    sync.add_argument("--database", default=None)
    report = sub.add_parser("report", help="Validate the local database without downloading.")
    report.add_argument("--database", default=None)
    report.add_argument("--symbols", default=None)
    report.add_argument("--start", default=None)
    report.add_argument("--end", default=None)
    report.add_argument("--feed", choices=["sip", "iex"], default=None)
    args = parser.parse_args(argv)
    try:
        settings = get_settings()
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    database = args.database or settings.market_data_path
    if args.command == "report":
        _print_status(
            database,
            start=None if args.start is None else date.fromisoformat(args.start),
            end=None if args.end is None else date.fromisoformat(args.end),
            symbols=None
            if args.symbols is None
            else [part.strip().upper() for part in args.symbols.split(",") if part.strip()],
            feed=args.feed,
        )
        return
    _sync(settings, database, args.symbols, args.start, args.end, args.feed)


def _sync(
    settings: Settings,
    database: str,
    symbols_text: str,
    start_text: str,
    end_text: str | None,
    feed: str,
) -> None:
    key = settings.alpaca_api_key
    secret = settings.alpaca_api_secret
    if key is None or secret is None:
        print(
            "Alpaca credentials are not configured. Set both keys in .env. "
            "Do not paste them into chat.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    symbols = [part.strip().upper() for part in symbols_text.split(",") if part.strip()]
    start = date.fromisoformat(start_text)
    end = date.fromisoformat(end_text) if end_text else latest_safe_session(datetime.now(UTC), feed)
    print(f"feed={feed} adjustment=raw timeframe=1Day symbols={','.join(symbols)}")
    print(f"window={start.isoformat()}..{end.isoformat()} database={database}")
    if feed == "sip":
        print("Using SIP. If this account is not entitled, rerun the same command with --feed iex.")
    store = MarketStore(database)
    client = AlpacaDailyBars(key.get_secret_value(), secret.get_secret_value())
    try:
        result = sync_daily_bars(store, client.fetch, symbols, start, end, feed)
    except MarketDataError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    counts = result.counts
    print(
        f"fetched={counts.fetched} inserted={counts.inserted} "
        f"unchanged={counts.unchanged} conflicts={counts.conflicts}"
    )
    for warning in result.warnings:
        print(f"warning: {warning}")
    _print_status(database)


def _print_status(
    database: str,
    start: date | None = None,
    end: date | None = None,
    symbols: list[str] | None = None,
    feed: str | None = None,
) -> None:
    status = market_data_status(database, start=start, end=end, symbols=symbols, feed=feed)
    print(
        f"requested={status.requested_start}..{status.requested_end} "
        f"feed={status.requested_feed or 'none'}"
    )
    print(f"bars={status.bar_count} stored={status.earliest_session}..{status.latest_session}")
    print(f"last_success={status.last_successful_ingestion}")
    print(f"coverage_complete={status.coverage_complete}")
    print(f"suitable_for_research={status.suitable_for_research}")
    for item in status.coverage:
        print(
            f"{item.symbol} {item.feed} rows={item.bar_count} "
            f"{item.earliest_session}..{item.latest_session} "
            f"missing_start={item.missing_start} missing_middle={item.missing_middle} "
            f"missing_end={item.missing_end}"
        )
    for warning in status.warnings:
        print(f"warning: {warning}")
    print(status.caveat)
