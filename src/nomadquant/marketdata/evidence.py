"""What the stored bars are allowed to prove. This module does not download data."""

from __future__ import annotations

from typing import Any

from nomadquant.marketdata.validate import ADJUSTMENT, PROVIDER, TIMEFRAME


def dataset_evidence() -> dict[str, Any]:
    """The store keeps Alpaca raw daily bars. It does not contain corporate actions.

    A later split-adjusted or dividend-adjusted series would be a separate dataset.
    Mixing one into the raw experiments would change their results, so it is absent.
    """
    return {
        "provider": PROVIDER,
        "adjustment": ADJUSTMENT,
        "timeframe": TIMEFRAME,
        "feeds": ["iex", "sip"],
        "feeds_are_distinct": True,
        "corporate_actions": "absent",
        "split_adjusted_dataset": False,
        "dividend_adjusted_dataset": False,
        "point_in_time_total_return": False,
        "research_state": "NOT_EVALUABLE",
        "reason": "authoritative_corporate_actions_not_stored",
        "permission_to_trade": False,
    }
