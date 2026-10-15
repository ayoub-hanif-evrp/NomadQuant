"""Configuration locks."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from nomadquant.config import PAPER_API_URL, Settings
from tests.conftest import make_settings


def test_defaults_are_paper_only(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    assert settings.trading_mode == "paper"
    assert settings.initial_virtual_capital_usd == 100
    assert settings.allow_order_submission is False
    assert settings.alpaca_base_url == PAPER_API_URL
    assert settings.api_host == "127.0.0.1"
    assert settings.credentials_configured is False


@pytest.mark.parametrize("mode", ["live", "LIVE", "real", "paper-live"])
def test_live_trading_mode_is_rejected(tmp_path: Path, mode: str) -> None:
    with pytest.raises(ValidationError, match="paper"):
        make_settings(tmp_path, trading_mode=mode)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.alpaca.markets",
        "https://api.alpaca.markets/",
        "http://paper-api.alpaca.markets",
        "https://live-api.alpaca.markets",
        "https://paper-api.alpaca.markets/v2",
        "https://user:pass@paper-api.alpaca.markets",
    ],
)
def test_non_paper_alpaca_urls_are_rejected(tmp_path: Path, url: str) -> None:
    with pytest.raises(ValidationError, match="ALPACA_BASE_URL"):
        make_settings(tmp_path, alpaca_base_url=url)


def test_order_submission_cannot_be_enabled(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="ALLOW_ORDER_SUBMISSION"):
        make_settings(tmp_path, allow_order_submission=True)


def test_virtual_capital_is_locked(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="100"):
        make_settings(tmp_path, initial_virtual_capital_usd=100_000)


def test_public_bind_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="127.0.0.1"):
        make_settings(tmp_path, api_host="0.0.0.0")


def test_blank_credentials_are_absent(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, alpaca_api_key="  ", alpaca_api_secret="")
    assert settings.credentials_configured is False


def test_partial_credentials_are_rejected(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, alpaca_api_key="paper-key")
    with pytest.raises(ValueError, match="both"):
        settings.require_consistent_credentials()


def test_settings_model_accepts_explicit_construction() -> None:
    settings = Settings.model_validate(
        {
            "trading_mode": "paper",
            "initial_virtual_capital_usd": 100,
            "allow_order_submission": False,
        }
    )
    assert isinstance(settings, Settings)
