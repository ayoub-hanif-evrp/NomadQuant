"""Chronological research check. The result is not a broker fill."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from nomadquant.daily.engine import primary_candidate


def walk_forward(
    prices: dict[str, dict[date, Decimal]],
    sessions: list[date],
    *,
    folds: int = 3,
) -> dict[str, object]:
    usable = [day for day in sessions if day in (prices.get("SPY") or {})]
    if len(usable) < 220 or folds < 2:
        return {"label": "historical_research", "status": "insufficient_history", "folds": []}
    start = 200
    span = usable[start:]
    width = max(1, len(span) // folds)
    reports: list[dict[str, str]] = []
    for index in range(folds):
        window = span[index * width : (index + 1) * width]
        hypothetical = Decimal("0")
        trades = 0
        for cursor, day in enumerate(window[:-1]):
            choice = primary_candidate(prices, day)
            if choice is None or choice["action"] != "BUY" or choice["symbol"] != "SPY":
                continue
            today = prices["SPY"][day]
            nxt = prices["SPY"].get(window[cursor + 1])
            if nxt is None or today <= 0:
                continue
            change = nxt / today - Decimal("1") - Decimal("0.0001")
            hypothetical += change
            trades += 1
        reports.append(
            {
                "fold": str(index + 1),
                "hypothetical_return": format(hypothetical, "f"),
                "buy_days": str(trades),
                "label": "hypothetical_not_broker",
            }
        )
    return {"label": "historical_research", "status": "completed", "folds": reports}
