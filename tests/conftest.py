"""Shared fixtures. Tests never read a developer .env or the network."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nomadquant.api.app import create_app
from nomadquant.config import Settings, get_settings

_ENV_VARS = (
    "TRADING_MODE",
    "INITIAL_VIRTUAL_CAPITAL_USD",
    "ALLOW_ORDER_SUBMISSION",
    "ALPACA_API_KEY",
    "ALPACA_API_SECRET",
    "ALPACA_BASE_URL",
    "API_HOST",
    "API_PORT",
    "DATABASE_PATH",
    "MARKET_DATA_PATH",
    "RESEARCH_PATH",
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL",
    "AGENTS_PATH",
    "AGENT_MEMO_ROOT",
)


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_path": str(tmp_path / "nomadquant.db"),
        "market_data_path": str(tmp_path / "market.sqlite"),
        "research_path": str(tmp_path / "research.sqlite"),
        "agents_path": str(tmp_path / "agents.sqlite"),
        "agent_memo_root": str(tmp_path / "agent-memos"),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as test_client:
        yield test_client
