"""FastAPI application. Every route is read-only."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from nomadquant.api.agent_routes import router as agent_router
from nomadquant.api.approval_routes import router as approval_router
from nomadquant.api.market_routes import router as market_router
from nomadquant.api.observe import router as observability_router
from nomadquant.api.research_routes import router as research_router
from nomadquant.api.risk_routes import router as risk_router
from nomadquant.api.schemas import (
    BrokerAccountResponse,
    BrokerPositionsResponse,
    HealthResponse,
    SystemStatusResponse,
)
from nomadquant.api.shadow_routes import router as shadow_router
from nomadquant.audit import AuditLog
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
        app.state.audit.record_event(
            event_type="system.startup",
            event_level="info",
            component="system",
            status="succeeded",
            title="API started",
            summary="NomadQuant API started in paper mode with order submission disabled.",
        )
        logger.info(
            "nomadquant_started trading_mode=%s allow_order_submission=%s "
            "credentials_configured=%s",
            app.state.settings.trading_mode,
            app.state.settings.allow_order_submission,
            app.state.settings.credentials_configured,
        )
        yield
        app.state.audit.record_event(
            event_type="system.shutdown",
            event_level="info",
            component="system",
            status="succeeded",
            title="API stopped",
            summary="NomadQuant API stopped.",
        )

    app = FastAPI(
        title="NomadQuant",
        version="1.0.1",
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
    app.state.audit = AuditLog(active.database_path, active.secret_values)
    app.state.broker = AlpacaReadOnlyBroker(active, audit=app.state.audit)
    app.include_router(market_router)
    app.include_router(observability_router)
    app.include_router(research_router)
    app.include_router(agent_router)
    app.include_router(risk_router)
    app.include_router(shadow_router)
    app.include_router(approval_router)

    @app.exception_handler(Exception)
    async def unhandled(request: object, exc: Exception) -> JSONResponse:
        if isinstance(exc, HTTPException):
            detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
            if exc.status_code >= 500:
                app.state.audit.record_event(
                    event_type="api.error",
                    event_level="error",
                    component="system",
                    status="failed",
                    title="API request failed",
                    summary="An API request failed. Details were withheld.",
                    error_code="http_error",
                    error_message_safe="An API request failed. Details were withheld.",
                )
            return JSONResponse(status_code=exc.status_code, content={"detail": detail})
        app.state.audit.record_event(
            event_type="api.error",
            event_level="error",
            component="system",
            status="failed",
            title="API request failed",
            summary="An API request failed. Details were withheld.",
            error_code=type(exc).__name__,
            error_message_safe="An API request failed. Details were withheld.",
        )
        return JSONResponse(status_code=500, content={"detail": "Request failed."})

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
