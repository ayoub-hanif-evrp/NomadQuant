"""HTTP API behavior without a network."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nomadquant.api.app import create_app
from nomadquant.api.schemas import (
    BrokerAccountResponse,
    BrokerPositionsResponse,
    HealthResponse,
    SystemStatusResponse,
)
from nomadquant.broker.alpaca import AlpacaReadOnlyBroker
from tests.conftest import make_settings

_PLANTED_SECRET = "PLANTED-ALPACA-SECRET-9f3c"


class _Account:
    equity = "100000"
    buying_power = "25000.50"
    cash = "80000"
    currency = "USD"
    status = "ACTIVE"


class _Position:
    symbol = "SPY"
    qty = "0.15"
    side = "long"
    market_value = "80.10"
    avg_entry_price = "530"
    unrealized_pl = "0.40"


class _ConnectedClient:
    def get_account(self) -> _Account:
        return _Account()

    def get_all_positions(self) -> list[_Position]:
        return [_Position()]


class _LeakyClient:
    def get_account(self) -> None:
        raise RuntimeError(f"upstream failed token={_PLANTED_SECRET}")

    def get_all_positions(self) -> None:
        raise AssertionError("positions must not be requested after account failure")


class _RateLimitError(Exception):
    status_code = 429


class _RateLimitedClient:
    def get_account(self) -> None:
        raise _RateLimitError(f"slow down {_PLANTED_SECRET}")

    def get_all_positions(self) -> None:
        raise AssertionError("positions must not be requested after rate limit")


def test_health_without_credentials(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = HealthResponse.model_validate(response.json())
    assert body.status == "ok"


def test_status_reports_paper_defaults(client: TestClient) -> None:
    response = client.get("/api/system/status")
    assert response.status_code == 200
    body = SystemStatusResponse.model_validate(response.json())
    assert body.trading_mode == "paper"
    assert body.paper_only is True
    assert body.allow_order_submission is False
    assert body.initial_virtual_capital_usd == 100
    assert body.credentials_configured is False
    assert body.broker_status == "disconnected"
    assert body.failure_kind is None
    assert body.alpaca_base_url == "https://paper-api.alpaca.markets"
    assert body.api_host == "127.0.0.1"
    assert body.database_ok is True


def test_disconnected_account_and_positions(client: TestClient) -> None:
    account = client.get("/api/broker/account")
    positions = client.get("/api/broker/positions")
    assert account.status_code == 200
    assert positions.status_code == 200
    account_body = BrokerAccountResponse.model_validate(account.json())
    positions_body = BrokerPositionsResponse.model_validate(positions.json())
    assert account_body.status == "disconnected"
    assert account_body.account is None
    assert account_body.virtual_capital_usd == 100
    assert positions_body.status == "disconnected"
    assert positions_body.positions == []


def test_mocked_alpaca_account_is_distinct_from_virtual_capital(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        alpaca_api_key="paper-key",
        alpaca_api_secret="paper-secret",
    )
    app = create_app(settings)
    app.state.broker = AlpacaReadOnlyBroker(settings, client=_ConnectedClient())
    with TestClient(app) as test_client:
        response = test_client.get("/api/broker/account")
        positions = test_client.get("/api/broker/positions")
    account_body = BrokerAccountResponse.model_validate(response.json())
    positions_body = BrokerPositionsResponse.model_validate(positions.json())
    assert account_body.status == "connected"
    assert account_body.account is not None
    assert account_body.account.equity == "100000"
    assert account_body.account.buying_power == "25000.50"
    assert account_body.virtual_capital_usd == 100
    assert account_body.account.equity != "100"
    assert positions_body.positions[0].symbol == "SPY"
    assert positions_body.positions[0].qty == "0.15"


def test_broker_errors_do_not_reveal_credentials(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        alpaca_api_key="paper-key",
        alpaca_api_secret=_PLANTED_SECRET,
    )
    app = create_app(settings)
    app.state.broker = AlpacaReadOnlyBroker(settings, client=_LeakyClient())
    with TestClient(app) as test_client:
        response = test_client.get("/api/broker/account")
    assert response.status_code == 200
    assert _PLANTED_SECRET not in response.text
    body = BrokerAccountResponse.model_validate(response.json())
    assert body.status == "error"
    assert body.failure_kind == "broker"
    assert body.message == "Alpaca request failed. Details were withheld."


def test_authentication_failure_is_classified_without_leaking_secrets(tmp_path: Path) -> None:
    class _AuthError(Exception):
        status_code = 401

    class _AuthClient:
        def get_account(self) -> None:
            raise _AuthError(f"rejected {_PLANTED_SECRET}")

        def get_all_positions(self) -> None:
            raise AssertionError("positions must not be requested after authentication failure")

    settings = make_settings(
        tmp_path,
        alpaca_api_key="paper-key",
        alpaca_api_secret=_PLANTED_SECRET,
    )
    app = create_app(settings)
    app.state.broker = AlpacaReadOnlyBroker(settings, client=_AuthClient())
    with TestClient(app) as test_client:
        response = test_client.get("/api/broker/account")
    assert _PLANTED_SECRET not in response.text
    body = BrokerAccountResponse.model_validate(response.json())
    assert body.status == "error"
    assert body.failure_kind == "authentication"
    assert body.account is None


def test_network_failure_is_classified_without_leaking_secrets(tmp_path: Path) -> None:
    class _NetClient:
        def get_account(self) -> None:
            raise ConnectionError(f"unreachable {_PLANTED_SECRET}")

        def get_all_positions(self) -> None:
            raise AssertionError("positions must not be requested after a network failure")

    settings = make_settings(
        tmp_path,
        alpaca_api_key="paper-key",
        alpaca_api_secret=_PLANTED_SECRET,
    )
    app = create_app(settings)
    app.state.broker = AlpacaReadOnlyBroker(settings, client=_NetClient())
    with TestClient(app) as test_client:
        response = test_client.get("/api/system/status")
    assert _PLANTED_SECRET not in response.text
    body = SystemStatusResponse.model_validate(response.json())
    assert body.broker_status == "error"
    assert body.failure_kind == "network"
    assert body.allow_order_submission is False


def test_rate_limit_is_visible_and_redacted(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        alpaca_api_key="paper-key",
        alpaca_api_secret=_PLANTED_SECRET,
    )
    app = create_app(settings)
    app.state.broker = AlpacaReadOnlyBroker(settings, client=_RateLimitedClient())
    with TestClient(app) as test_client:
        response = test_client.get("/api/broker/positions")
    assert response.status_code == 200
    assert _PLANTED_SECRET not in response.text
    body = BrokerPositionsResponse.model_validate(response.json())
    assert body.status == "rate_limited"
    assert body.positions == []


def test_no_order_submission_endpoint(client: TestClient) -> None:
    schema = client.app.openapi()
    paths = schema["paths"]
    assert set(paths) == {
        "/health",
        "/api/system/status",
        "/api/broker/account",
        "/api/broker/positions",
        "/api/paper/status",
        "/api/daily/status",
        "/api/market-data/status",
        "/api/market-data/bars",
        "/api/observability/overview",
        "/api/observability/events",
        "/api/observability/events/histogram",
        "/api/observability/events/{event_id}",
        "/api/observability/runs",
        "/api/observability/runs/{run_id}",
        "/api/observability/decision-traces",
        "/api/observability/decision-traces/{decision_id}",
        "/api/observability/system-health",
        "/api/research/experiments",
        "/api/research/experiments/{experiment_id}",
        "/api/research/runs",
        "/api/research/runs/{run_id}",
        "/api/research/runs/{run_id}/equity",
        "/api/research/runs/{run_id}/trades",
        "/api/research/runs/{run_id}/decisions",
        "/api/research/decisions/{decision_id}",
        "/api/research/runs/{run_id}/replay",
        "/api/research/runs/{run_id}/card",
        "/api/research/runs/{run_id}/verify",
        "/api/agents/status",
        "/api/agents/benchmarks",
        "/api/agents/runs",
        "/api/agents/runs/{run_id}",
        "/api/risk/status",
        "/api/risk/evaluations",
        "/api/risk/evaluations/{evaluation_id}",
        "/api/shadow/status",
        "/api/shadow/valuation",
        "/api/shadow/performance",
        "/api/shadow/ops",
        "/api/shadow/timeline",
        "/api/shadow/cycles",
        "/api/shadow/cycles/{cycle_id}",
        "/api/shadow/cycles/{cycle_id}/verification",
        "/api/shadow/pilot",
        "/api/shadow/pilot/preview",
        "/api/shadow/pilot/confirm",
        "/api/shadow/quality",
        "/api/shadow/equity",
        "/api/shadow/preflight",
        "/api/shadow/reconcile",
        "/api/approvals/inbox",
        "/api/approvals/{request_id}",
        "/api/approvals/{request_id}/decide",
        "/api/market-data/freshness",
        "/api/market-data/live-quote",
        "/api/overview",
        "/api/market-data/sync",
        "/api/copilot/ask",
        "/api/news/headlines",
        "/api/news/refresh",
        "/api/news/analyze",
        "/api/agents/reviews",
        "/api/agents/jobs",
        "/api/agents/jobs/{job_id}",
        "/api/lab/latest",
        "/api/lab/run",
    }
    from nomadquant.api.mutations import assert_route_safety

    assert_route_safety(paths)


def test_broker_module_has_no_order_methods() -> None:
    source = Path("src/nomadquant/broker/alpaca.py").read_text(encoding="utf-8")
    for token in (
        "submit_order",
        "cancel_order",
        "replace_order",
        "close_position",
        "close_all_positions",
        "liquidate",
    ):
        assert token not in source


def test_trading_client_is_constructed_for_paper_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    class _DummyClient:
        def __init__(
            self,
            key: str,
            secret: str,
            paper: bool = False,
            url_override: str = "",
        ) -> None:
            captured["key"] = key
            captured["secret"] = secret
            captured["paper"] = paper
            captured["url_override"] = url_override

        def get_account(self) -> _Account:
            return _Account()

        def get_all_positions(self) -> list[_Position]:
            return []

    monkeypatch.setattr("alpaca.trading.client.TradingClient", _DummyClient)
    settings = make_settings(
        tmp_path,
        alpaca_api_key="paper-key",
        alpaca_api_secret="paper-secret",
    )
    broker = AlpacaReadOnlyBroker(settings)
    account = broker.account()
    assert account.status == "connected"
    assert captured == {
        "key": "paper-key",
        "secret": "paper-secret",
        "paper": True,
        "url_override": "https://paper-api.alpaca.markets",
    }


def test_market_data_status_does_not_create_a_database(client: TestClient, tmp_path: Path) -> None:
    path = tmp_path / "market.sqlite"
    response = client.get("/api/market-data/status")
    assert response.status_code == 200
    body = response.json()
    assert body["bar_count"] == 0
    assert body["suitable_for_research"] is False
    assert "dividend-adjusted" in body["caveat"]
    assert "point-in-time" in body["caveat"]
    assert not path.exists()
