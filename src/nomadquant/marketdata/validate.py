"""Checks applied before a daily bar is stored. Invalid rows are rejected."""

from datetime import date, datetime
from decimal import Decimal

from nomadquant.marketdata.availability import session_date_from_timestamp
from nomadquant.marketdata.calendar import is_session
from nomadquant.marketdata.errors import InvalidBar

PROVIDER = "alpaca"
ADJUSTMENT = "raw"
TIMEFRAME = "1Day"
CURRENCY = "USD"


def parse_price(value: object, field: str, symbol: str) -> Decimal:
    price = _decimal(value, symbol, field)
    if price <= 0:
        raise InvalidBar(f"{symbol} {field} must be a positive price.")
    return price


def parse_volume(value: object, symbol: str) -> Decimal:
    volume = _decimal(value, symbol, "volume")
    if volume < 0:
        raise InvalidBar(f"{symbol} volume must be nonnegative.")
    return volume


def _decimal(value: object, symbol: str, field: str) -> Decimal:
    text = format(value, "f") if isinstance(value, float) else str(value)
    try:
        number = Decimal(text)
    except Exception as exc:
        raise InvalidBar(f"{symbol} {field} is not a number.") from exc
    if not number.is_finite():
        raise InvalidBar(f"{symbol} {field} is not a finite number.")
    plain = format(number, "f")
    if "." in plain:
        plain = plain.rstrip("0").rstrip(".")
    return Decimal(plain if plain else "0")


def require_consistent_ohlc(
    symbol: str,
    open_: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
) -> None:
    if low > open_ or low > close or low > high or open_ > high or close > high:
        raise InvalidBar(f"{symbol} OHLC is inconsistent.")


def require_session_timestamp(symbol: str, timestamp: datetime) -> date:
    if timestamp.tzinfo is None:
        raise InvalidBar(f"{symbol} bar timestamp must be timezone-aware.")
    session = session_date_from_timestamp(timestamp)
    if not is_session(session):
        raise InvalidBar(f"{symbol} {session.isoformat()} is not an NYSE session.")
    return session
