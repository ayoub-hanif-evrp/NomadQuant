"""Dataset fingerprints for reproducible experiments."""

import hashlib
import json
from datetime import date
from pathlib import Path

from nomadquant.marketdata.store import MarketStore


def dataset_fingerprint(
    market_path: str | Path,
    *,
    symbols: list[str],
    feed: str,
    start: date,
    end: date,
) -> dict[str, object]:
    store = MarketStore(market_path)
    hasher = hashlib.sha256()
    rows = 0
    revisions = 0
    for symbol in symbols:
        for session, content_hash in store.bar_hashes(symbol, feed, start, end):
            rows += 1
            hasher.update(f"{symbol}|{session.isoformat()}|{content_hash}\n".encode())
        revisions += store.revision_count(symbol, feed, start, end)
    return {
        "algorithm": "sha256",
        "digest": hasher.hexdigest(),
        "symbols": symbols,
        "feed": feed,
        "adjustment": "raw",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "bar_count": rows,
        "revision_count": revisions,
        "encoding": "symbol|session_date|content_hash newline",
    }


def fingerprint_text(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
