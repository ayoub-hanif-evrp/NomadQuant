"""Read-only Alpaca corporate-action download. This module submits no orders."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from nomadquant.marketdata.actions import ActionDownload, ActionStore, collect_action_pages

DATA_HOST = "https://data.alpaca.markets"
_TYPES = (
    "forward_split,reverse_split,unit_split,cash_dividend,stock_dividend,"
    "spin_off,cash_merger,stock_merger,stock_and_cash_merger,redemption,"
    "name_change,worthless_removal,rights_distribution,capital_gains_distribution"
)


def download_corporate_actions(
    store: ActionStore,
    fetch_page: Any,
    *,
    retrieved_at: datetime | None = None,
) -> ActionDownload:
    """Store a complete page set. An incomplete download writes nothing."""
    stamp = datetime.now(UTC) if retrieved_at is None else retrieved_at
    download = collect_action_pages(fetch_page, retrieved_at=stamp, source="alpaca")
    if download.complete:
        store.write(download.actions)
    return download


def alpaca_page_fetcher(
    api_key: str, secret_key: str, symbols: list[str], start: date, end: date
) -> Any:
    """Return a page function for the official v1 corporate-actions endpoint."""
    from alpaca.data.historical.stock import StockHistoricalDataClient

    client = StockHistoricalDataClient(api_key, secret_key, url_override=DATA_HOST)

    def fetch_page(token: str | None) -> dict[str, Any]:
        params: dict[str, str | int] = {
            "symbols": ",".join(symbols),
            "types": _TYPES,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": 1000,
            "sort": "asc",
        }
        if token:
            params["page_token"] = token
        payload = client.get("/corporate-actions", params, api_version="v1")
        if not isinstance(payload, dict):
            raise TypeError("corporate action page was not an object")
        return payload

    return fetch_page
