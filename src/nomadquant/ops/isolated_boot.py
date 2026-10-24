"""Start the local API from the process environment. Does not read .env."""

from __future__ import annotations

import sys

import uvicorn
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict

from nomadquant.api.app import create_app
from nomadquant.config import Settings


class IsolatedSettings(Settings):
    """Settings from the process environment, never from a .env file."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")


def main() -> None:
    try:
        settings = IsolatedSettings()
    except (ValidationError, ValueError) as exc:
        sys.stderr.write(f"Configuration error: {type(exc).__name__}\n")
        raise SystemExit(1) from exc
    if settings.credentials_configured:
        sys.stderr.write("Isolated boot refuses broker credentials.\n")
        raise SystemExit(2)
    uvicorn.run(
        create_app(settings),
        host=settings.api_host,
        port=settings.api_port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
