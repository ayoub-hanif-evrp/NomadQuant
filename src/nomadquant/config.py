"""Process configuration. Live trading and order submission cannot be enabled."""

from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PAPER_API_URL = "https://paper-api.alpaca.markets"
PAPER_API_HOST = "paper-api.alpaca.markets"


class Settings(BaseSettings):
    """Environment-backed settings. Invalid trading configuration fails startup."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    trading_mode: str = "paper"
    initial_virtual_capital_usd: float = 100
    allow_order_submission: bool = False
    alpaca_api_key: SecretStr | None = None
    alpaca_api_secret: SecretStr | None = None
    alpaca_base_url: str = PAPER_API_URL
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    database_path: str = "data/nomadquant.db"

    @field_validator("trading_mode")
    @classmethod
    def trading_mode_must_be_paper(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized != "paper":
            raise ValueError(
                "TRADING_MODE must be 'paper'. "
                f"Received {value!r}. Live trading is not implemented and is rejected."
            )
        return "paper"

    @field_validator("initial_virtual_capital_usd")
    @classmethod
    def capital_is_locked(cls, value: float) -> float:
        if value != 100:
            raise ValueError(
                "INITIAL_VIRTUAL_CAPITAL_USD must be 100. "
                "The figure is an internal strategy limit, not a broker balance."
            )
        return 100.0

    @field_validator("allow_order_submission")
    @classmethod
    def orders_stay_disabled(cls, value: bool) -> bool:
        if value:
            raise ValueError(
                "ALLOW_ORDER_SUBMISSION must be false. Order submission is not implemented."
            )
        return False

    @field_validator("alpaca_api_key", "alpaca_api_secret", mode="before")
    @classmethod
    def blank_secret_is_absent(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_validator("alpaca_base_url")
    @classmethod
    def alpaca_url_must_be_paper(cls, value: str) -> str:
        candidate = value.strip()
        if "live" in candidate.lower():
            raise ValueError(
                f"ALPACA_BASE_URL rejects live endpoints. The only allowed URL is {PAPER_API_URL}."
            )
        parsed = urlparse(candidate)
        if (
            parsed.scheme != "https"
            or parsed.hostname != PAPER_API_HOST
            or parsed.port not in (None, 443)
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError(
                f"ALPACA_BASE_URL must be exactly {PAPER_API_URL}. Received {value!r}."
            )
        return PAPER_API_URL

    @field_validator("api_host")
    @classmethod
    def api_binds_locally(cls, value: str) -> str:
        if value != "127.0.0.1":
            raise ValueError(
                "API_HOST must be 127.0.0.1. Binding on 0.0.0.0 or another interface is rejected."
            )
        return value

    @property
    def credentials_configured(self) -> bool:
        return self.alpaca_api_key is not None and self.alpaca_api_secret is not None

    @property
    def secret_values(self) -> list[str]:
        values: list[str] = []
        for secret in (self.alpaca_api_key, self.alpaca_api_secret):
            if secret is None:
                continue
            raw = secret.get_secret_value().strip()
            if raw:
                values.append(raw)
        return values

    def require_consistent_credentials(self) -> None:
        key_set = self.alpaca_api_key is not None
        secret_set = self.alpaca_api_secret is not None
        if key_set != secret_set:
            raise ValueError(
                "Set both ALPACA_API_KEY and ALPACA_API_SECRET, or leave both empty "
                "to start in disconnected mode."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.require_consistent_credentials()
    return settings
