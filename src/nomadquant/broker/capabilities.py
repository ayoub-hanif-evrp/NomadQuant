"""Read-only description of Alpaca capabilities. This module submits nothing.

Official sources, retrieved 2026-10-16:

- https://docs.alpaca.markets/us/docs/fractional-trading
- https://docs.alpaca.markets/us/docs/working-with-orders
- https://docs.alpaca.markets/us/docs/paper-trading
- https://docs.alpaca.markets/us/reference/postorder

The user's paper account was not queried and must not be reset. Alpaca's
default paper balance is not NomadQuant's internal $100 ledger.
"""

from __future__ import annotations

from typing import Any

PROFILE_VERSION = "alpaca-readonly-2026-10-16"


def broker_capability_profile() -> dict[str, Any]:
    return {
        "profile_version": PROFILE_VERSION,
        "broker": "alpaca",
        "order_submission_implemented": False,
        "account_queried": False,
        "paper_balance_assumed_usd": None,
        "internal_capital_constraint_usd": "100",
        "sources": [
            "https://docs.alpaca.markets/us/docs/fractional-trading",
            "https://docs.alpaca.markets/us/docs/working-with-orders",
            "https://docs.alpaca.markets/us/docs/paper-trading",
            "https://docs.alpaca.markets/us/reference/postorder",
        ],
        "fractional_shares": {
            "documented": (
                "Alpaca says accounts can trade fractional shares in live and paper "
                "by default, only when the asset fractionable flag is true."
            ),
            "spy_fractionable": "NOT_QUERIED",
        },
        "minimum_notional": {
            "documented": "Notional and qty cannot both be sent. No universal minimum confirmed.",
            "value": None,
        },
        "quantity_precision": {
            "documented": "Fractional qty is allowed for supported market and day orders.",
            "asset_precision": "NOT_QUERIED",
        },
        "order_types": ["market", "limit", "stop", "stop_limit", "trailing_stop"],
        "time_in_force": {
            "fractional": "day",
            "equity": ["day", "gtc", "opg", "cls", "ioc", "fok"],
            "note": "Extended hours are documented for limit orders, not for market orders.",
        },
        "fees": {
            "documented": "Fractional fees are documented to work the same way as whole shares.",
            "schedule": "NOT_VERIFIED",
        },
        "paper_fills": {
            "documented": (
                "Paper orders fill when marketable. Paper does not simulate dividends. "
                "A non-marketable limit is not filled until it crosses the quote."
            )
        },
        "client_order_id": {
            "documented": "Unique, at most 128 characters, and lookup is by that id.",
            "timeout": (
                "Alpaca says a timeout does not mean the order failed and must not be resent "
                "until the broker record is confirmed."
            ),
        },
        "paper_reset": {
            "documented": (
                "The dashboard can create or delete paper accounts and set a starting balance. "
                "Balance changes require a reset and can replace keys and history."
            ),
            "action_taken": "none",
        },
        "uncertainties": [
            "This process did not call the assets or account endpoints.",
            "SPY fractionable status and the paper cash balance are unknown.",
            "Do not treat the internal $100 shadow book as the Alpaca paper equity.",
        ],
    }
