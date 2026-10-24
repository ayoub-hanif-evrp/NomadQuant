"""Local commands for daily-bar sync and the offline quality report."""

import argparse
import sys
from datetime import UTC, date, datetime

from nomadquant.audit import AuditLog
from nomadquant.config import Settings, get_settings
from nomadquant.marketdata.action_client import alpaca_page_fetcher, download_corporate_actions
from nomadquant.marketdata.actions import ActionStore
from nomadquant.marketdata.alpaca_bars import AlpacaDailyBars
from nomadquant.marketdata.availability import latest_safe_session
from nomadquant.marketdata.errors import MarketDataError
from nomadquant.marketdata.report import MarketDataStatus, market_data_status
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
    actions = sub.add_parser(
        "actions", help="Download corporate actions. Does not change raw bars."
    )
    actions.add_argument("--symbols", default="SPY,QQQ")
    actions.add_argument("--start", required=True)
    actions.add_argument("--end", default=None)
    actions.add_argument("--database", default=None)
    args = parser.parse_args(argv)
    try:
        settings = get_settings()
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    database = args.database or settings.market_data_path
    audit = AuditLog(settings.database_path, settings.secret_values)
    if args.command == "actions":
        _actions(settings, database, args.symbols, args.start, args.end)
        return
    if args.command == "report":
        status = _print_status(
            database,
            start=None if args.start is None else date.fromisoformat(args.start),
            end=None if args.end is None else date.fromisoformat(args.end),
            symbols=None
            if args.symbols is None
            else [part.strip().upper() for part in args.symbols.split(",") if part.strip()],
            feed=args.feed,
        )
        _record_report(audit, status)
        return
    _sync(settings, audit, database, args.symbols, args.start, args.end, args.feed)


def _actions(
    settings: Settings,
    database: str,
    symbols_text: str,
    start_text: str,
    end_text: str | None,
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
    end = date.fromisoformat(end_text) if end_text else datetime.now(UTC).date()
    print(f"symbols={','.join(symbols)} window={start.isoformat()}..{end.isoformat()}")
    print("adjustment=corporate_actions. Raw bars are not modified.")
    store = ActionStore(database)
    try:
        download = download_corporate_actions(
            store,
            alpaca_page_fetcher(
                key.get_secret_value(),
                secret.get_secret_value(),
                symbols,
                start,
                end,
            ),
        )
    except Exception as exc:
        print(f"corporate action download failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
    if not download.complete:
        print(f"incomplete reason={download.reason} pages={download.pages}. Nothing was stored.")
        raise SystemExit(1)
    print(f"stored={len(download.actions)} pages={download.pages} point_in_time_total_return=false")
    print(
        "These rows use Alpaca process_date. That is not an announcement time, "
        "so the strategies stay NOT_EVALUABLE."
    )


def _sync(
    settings: Settings,
    audit: AuditLog,
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
    run_id = audit.start_run(
        run_type="market_data_sync",
        component="market_data",
        title="Market data sync",
        summary=f"{','.join(symbols)} {feed} {start.isoformat()}..{end.isoformat()}",
        payload={"symbols": symbols, "feed": feed, "database": database},
    )
    audit.record_event(
        event_type="market_data.sync.started",
        event_level="info",
        component="market_data",
        status="started",
        title="Market data sync started",
        summary=f"{','.join(symbols)} {feed} {start.isoformat()}..{end.isoformat()}",
        run_id=run_id,
    )
    try:
        result = sync_daily_bars(store, client.fetch, symbols, start, end, feed)
    except MarketDataError as exc:
        message = str(exc)
        audit.finish_run(
            run_id,
            status="failed",
            summary=message,
            error_code=type(exc).__name__,
            error_message_safe=message,
        )
        audit.record_event(
            event_type="market_data.sync.failed",
            event_level="error",
            component="market_data",
            status="failed",
            title="Market data sync failed",
            summary=message,
            run_id=run_id,
            error_code=type(exc).__name__,
            error_message_safe=message,
        )
        print(message, file=sys.stderr)
        raise SystemExit(1) from None
    outcome = "succeeded" if result.status == "success" else "warning"
    summary = (
        f"fetched={result.counts.fetched} inserted={result.counts.inserted} "
        f"unchanged={result.counts.unchanged} conflicts={result.counts.conflicts}"
    )
    audit.finish_run(run_id, status=outcome, summary=summary, payload={"warnings": result.warnings})
    audit.record_event(
        event_type="market_data.sync.finished",
        event_level="info" if outcome == "succeeded" else "warning",
        component="market_data",
        status=outcome,
        title="Market data sync finished",
        summary=summary,
        run_id=run_id,
    )
    if result.warnings:
        audit.record_event(
            event_type="market_data.quality",
            event_level="warning",
            component="market_data",
            status="warning",
            title="Market data quality notes",
            summary=f"{len(result.warnings)} quality notes were recorded.",
            run_id=run_id,
            payload={"warnings": result.warnings[:20]},
        )
    counts = result.counts
    print(
        f"fetched={counts.fetched} inserted={counts.inserted} "
        f"unchanged={counts.unchanged} conflicts={counts.conflicts}"
    )
    for warning in result.warnings:
        print(f"warning: {warning}")
    _print_status(database)


def _record_report(audit: AuditLog, status: MarketDataStatus) -> None:
    level = "info" if status.suitable_for_research else "warning"
    run_status = "succeeded" if status.coverage_complete else "warning"
    audit.record_event(
        event_type="market_data.report",
        event_level=level,
        component="market_data",
        status=run_status,
        title="Market data report",
        summary=(
            f"bars={status.bar_count} coverage_complete={status.coverage_complete} "
            f"suitable_for_research={status.suitable_for_research}"
        ),
        payload={"warnings": status.warnings[:20]},
    )


def _print_status(
    database: str,
    start: date | None = None,
    end: date | None = None,
    symbols: list[str] | None = None,
    feed: str | None = None,
) -> MarketDataStatus:
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
    return status
