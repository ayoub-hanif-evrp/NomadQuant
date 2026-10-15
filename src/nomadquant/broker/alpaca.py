"""Read-only Alpaca paper adapter.

This module never imports or calls order, cancel, or liquidation methods.
"""

import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from nomadquant.api.schemas import (
    AccountSnapshot,
    BrokerAccountResponse,
    BrokerPositionsResponse,
    BrokerStatus,
    PositionSnapshot,
)
from nomadquant.config import Settings
from nomadquant.logging import get_logger

logger = get_logger(__name__)

_ACCOUNT_CACHE_SECONDS = 5.0

_DISCONNECTED = "Alpaca credentials are not configured. The API is running in disconnected mode."
_RATE_LIMITED = "Alpaca rate limit reached. Try again later."
_FAILED = "Alpaca request failed. Details were withheld."


@dataclass(frozen=True)
class _CacheEntry:
    stored_at: float
    account: BrokerAccountResponse
    positions: BrokerPositionsResponse


def _decimal_text(value: object) -> str:
    try:
        return format(Decimal(str(value)), "f")
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Broker returned a non-decimal amount") from exc


def _status_code(exc: Exception) -> int | None:
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    response = getattr(exc, "response", None)
    response_code = getattr(response, "status_code", None)
    if isinstance(response_code, int):
        return response_code
    return None


def _plain(value: object) -> str:
    nested = getattr(value, "value", None)
    if isinstance(nested, str):
        return nested
    return str(value)


class AlpacaReadOnlyBroker:
    """Phase 1 paper reader.

    This is the concrete stand-in for ``PaperBroker``. It returns a status
    envelope instead of raising, so a missing credential or a broker failure
    does not take down the API. Order methods are not implemented.
    """

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client
        self._cache: _CacheEntry | None = None

    def _trading_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._settings.credentials_configured:
            return None
        from alpaca.trading.client import TradingClient

        key = self._settings.alpaca_api_key
        secret = self._settings.alpaca_api_secret
        if key is None or secret is None:
            return None
        self._client = TradingClient(
            key.get_secret_value(),
            secret.get_secret_value(),
            paper=True,
            url_override=self._settings.alpaca_base_url,
        )
        return self._client

    def read(self) -> _CacheEntry:
        now = time.monotonic()
        if self._cache is not None and now - self._cache.stored_at < _ACCOUNT_CACHE_SECONDS:
            return self._cache
        entry = self._read_uncached()
        self._cache = _CacheEntry(stored_at=now, account=entry.account, positions=entry.positions)
        return self._cache

    def account(self) -> BrokerAccountResponse:
        return self.read().account

    def positions(self) -> BrokerPositionsResponse:
        return self.read().positions

    def _read_uncached(self) -> _CacheEntry:
        capital = self._settings.initial_virtual_capital_usd
        client = self._trading_client()
        if client is None:
            return _CacheEntry(
                stored_at=time.monotonic(),
                account=BrokerAccountResponse(
                    status="disconnected",
                    message=_DISCONNECTED,
                    virtual_capital_usd=capital,
                    account=None,
                ),
                positions=BrokerPositionsResponse(status="disconnected", message=_DISCONNECTED),
            )
        try:
            raw_account = client.get_account()
            raw_positions = client.get_all_positions()
        except Exception as exc:
            status: BrokerStatus = "rate_limited" if _status_code(exc) == 429 else "error"
            message = _RATE_LIMITED if status == "rate_limited" else _FAILED
            logger.warning(
                "alpaca_read_failed error_type=%s status_code=%s",
                type(exc).__name__,
                _status_code(exc),
            )
            return _CacheEntry(
                stored_at=time.monotonic(),
                account=BrokerAccountResponse(
                    status=status,
                    message=message,
                    virtual_capital_usd=capital,
                    account=None,
                ),
                positions=BrokerPositionsResponse(status=status, message=message),
            )
        try:
            account = AccountSnapshot(
                equity=_decimal_text(raw_account.equity),
                buying_power=_decimal_text(raw_account.buying_power),
                cash=_decimal_text(raw_account.cash),
                currency=_plain(raw_account.currency),
                status=_plain(raw_account.status),
            )
            positions = [
                PositionSnapshot(
                    symbol=_plain(position.symbol),
                    qty=_decimal_text(position.qty),
                    side=_plain(position.side),
                    market_value=_decimal_text(position.market_value),
                    avg_entry_price=_decimal_text(position.avg_entry_price),
                    unrealized_pl=_decimal_text(position.unrealized_pl),
                )
                for position in raw_positions
            ]
        except (AttributeError, TypeError, ValueError):
            logger.warning("alpaca_read_failed error_type=InvalidPayload status_code=None")
            return _CacheEntry(
                stored_at=time.monotonic(),
                account=BrokerAccountResponse(
                    status="error",
                    message=_FAILED,
                    virtual_capital_usd=capital,
                    account=None,
                ),
                positions=BrokerPositionsResponse(status="error", message=_FAILED),
            )
        return _CacheEntry(
            stored_at=time.monotonic(),
            account=BrokerAccountResponse(
                status="connected",
                message=None,
                virtual_capital_usd=capital,
                account=account,
            ),
            positions=BrokerPositionsResponse(status="connected", positions=positions),
        )
