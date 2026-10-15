"""HTTP response models. Money from the broker is a decimal string."""

from typing import Literal

from pydantic import BaseModel, Field

BrokerStatus = Literal["connected", "disconnected", "error", "rate_limited"]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["nomadquant"] = "nomadquant"


class SystemStatusResponse(BaseModel):
    service: Literal["nomadquant"] = "nomadquant"
    trading_mode: Literal["paper"]
    paper_only: Literal[True] = True
    allow_order_submission: Literal[False]
    initial_virtual_capital_usd: float
    credentials_configured: bool
    broker_status: BrokerStatus
    broker_message: str | None = None
    database_ok: bool


class AccountSnapshot(BaseModel):
    equity: str
    buying_power: str
    cash: str
    currency: str
    status: str


class BrokerAccountResponse(BaseModel):
    status: BrokerStatus
    message: str | None = None
    virtual_capital_usd: float
    broker_equity_note: str = (
        "This $100 figure is NomadQuant's internal strategy limit. "
        "Alpaca paper equity, when connected, is the broker balance "
        "and is a different number."
    )
    account: AccountSnapshot | None = None


class PositionSnapshot(BaseModel):
    symbol: str
    qty: str
    side: str
    market_value: str
    avg_entry_price: str
    unrealized_pl: str


class BrokerPositionsResponse(BaseModel):
    status: BrokerStatus
    message: str | None = None
    positions: list[PositionSnapshot] = Field(default_factory=list)
