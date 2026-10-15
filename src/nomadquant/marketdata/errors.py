"""Market-data failures. Messages are safe to print."""


class MarketDataError(Exception):
    """Base error for ingestion and reads."""


class SipNotEntitled(MarketDataError):
    """SIP history is not available on this Alpaca account."""

    def __init__(self) -> None:
        super().__init__(
            "SIP historical data is not entitled for this account. "
            "Retry with --feed iex. IEX is a single-exchange feed and must stay "
            "separate from any SIP rows."
        )


class IncompleteSession(MarketDataError):
    """The requested end includes a US session that has not finished."""


class InvalidBar(MarketDataError):
    """A bar failed validation and was not stored."""


class MissingMarketData(MarketDataError):
    """A requested symbol has no stored bars for the selected feed."""


class IncompleteCoverage(MarketDataError):
    """Knowable sessions in the requested window are absent from the store."""
