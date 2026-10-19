"""Process configuration. Live trading and order submission cannot be enabled."""

from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PAPER_API_URL = "https://paper-api.alpaca.markets"
PAPER_API_HOST = "paper-api.alpaca.markets"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
LOCAL_OLLAMA_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def validate_ollama_base_url(value: str) -> str:
    """Return a normalized loopback-only Ollama URL or raise ValueError."""
    candidate = value.strip()
    if not candidate:
        raise ValueError("OLLAMA_BASE_URL must not be empty.")
    if "://" not in candidate:
        candidate = f"http://{candidate}"
    parsed = urlparse(candidate)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"OLLAMA_BASE_URL has an invalid port: {value!r}.") from exc
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "http"
        or host not in LOCAL_OLLAMA_HOSTS
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError(
            "OLLAMA_BASE_URL must be a plain http URL on localhost "
            f"(127.0.0.1, localhost or ::1). Received {value!r}."
        )
    rendered = f"[{host}]" if ":" in host else host
    return f"http://{rendered}:{port or 11434}"


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
    market_data_path: str = "data/market.sqlite"
    research_path: str = "data/research.sqlite"
    ollama_base_url: str = DEFAULT_OLLAMA_URL
    ollama_model: str = ""
    agents_path: str = "data/agents.sqlite"
    agent_memo_root: str = "data/agent-memos"
    agent_benchmark_path: str = "data/agent-benchmarks.sqlite"
    risk_path: str = "data/risk.sqlite"
    shadow_path: str = "data/shadow.sqlite"
    paper_path: str = "data/paper_orders.sqlite"
    approval_path: str = "data/approvals.sqlite"
    approval_outbox_dir: str = "data/approval-outbox"
    approval_ttl_minutes: int = 60
    approval_email_to: str = ""
    approval_email_from: str = "nomadquant@localhost"
    approval_public_base_url: str = "http://127.0.0.1:3000"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: SecretStr | None = None
    news_path: str = "data/news.sqlite"

    @field_validator("ollama_base_url")
    @classmethod
    def ollama_must_be_local(cls, value: str) -> str:
        return validate_ollama_base_url(value)

    @field_validator("ollama_model")
    @classmethod
    def ollama_model_is_trimmed(cls, value: str) -> str:
        return value.strip()

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

    @field_validator("alpaca_api_key", "alpaca_api_secret", "smtp_password", mode="before")
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
        for secret in (self.alpaca_api_key, self.alpaca_api_secret, self.smtp_password):
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
