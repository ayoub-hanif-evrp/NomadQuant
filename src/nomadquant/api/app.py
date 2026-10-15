"""FastAPI application. Every route is read-only."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nomadquant.api.schemas import (
    BrokerAccountResponse,
    BrokerPositionsResponse,
    HealthResponse,
    SystemStatusResponse,
)
from nomadquant.broker.alpaca import AlpacaReadOnlyBroker
from nomadquant.config import Settings, get_settings
from nomadquant.db import database_ok, init_db
from nomadquant.logging import configure_logging, get_logger
from nomadquant.marketdata.report import MarketDataStatus, market_data_status

logger = get_logger(__name__)

_LOCAL_ORIGINS = [
    "http://127.0.0.1:3000",
    "http://localhost:3000",
]


def create_app(settings: Settings | None = None) -> FastAPI:
    active = settings if settings is not None else get_settings()
    active.require_consistent_credentials()
    configure_logging(active)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        init_db(app.state.settings.database_path)
        logger.info(
            "nomadquant_started trading_mode=%s allow_order_submission=%s "
            "credentials_configured=%s",
            app.state.settings.trading_mode,
            app.state.settings.allow_order_submission,
            app.state.settings.credentials_configured,
        )
        yield

    app = FastAPI(
        title="NomadQuant",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_LOCAL_ORIGINS,
        allow_methods=["GET"],
        allow_headers=["Accept"],
    )
    app.state.settings = active
    app.state.broker = AlpacaReadOnlyBroker(active)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @app.get("/api/system/status", response_model=SystemStatusResponse)
    def system_status() -> SystemStatusResponse:
        broker: AlpacaReadOnlyBroker = app.state.broker
        account = broker.account()
        current: Settings = app.state.settings
        return SystemStatusResponse(
            trading_mode="paper",
            allow_order_submission=False,
            initial_virtual_capital_usd=current.initial_virtual_capital_usd,
            credentials_configured=current.credentials_configured,
            broker_status=account.status,
            broker_message=account.message,
            failure_kind=account.failure_kind,
            alpaca_base_url=current.alpaca_base_url,
            api_host=current.api_host,
            database_ok=database_ok(current.database_path),
        )

    @app.get("/api/broker/account", response_model=BrokerAccountResponse)
    def broker_account() -> BrokerAccountResponse:
        broker: AlpacaReadOnlyBroker = app.state.broker
        return broker.account()

    @app.get("/api/broker/positions", response_model=BrokerPositionsResponse)
    def broker_positions() -> BrokerPositionsResponse:
        broker: AlpacaReadOnlyBroker = app.state.broker
        return broker.positions()

    @app.get("/api/market-data/status", response_model=MarketDataStatus)
    def market_data() -> MarketDataStatus:
        current: Settings = app.state.settings
        return market_data_status(current.market_data_path)

    return app
