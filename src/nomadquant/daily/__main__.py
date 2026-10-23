"""Read-only daily desk entry point. It does not submit an order."""

from __future__ import annotations

import json

from nomadquant.config import Settings
from nomadquant.daily.cycle import daily_status


def main() -> None:
    report = daily_status(Settings())
    report["broker_orders_submitted_by_this_request"] = False
    print(json.dumps(report, default=str))


if __name__ == "__main__":
    main()
