"""Local API process. Binds to 127.0.0.1."""

import sys

import uvicorn
from pydantic import ValidationError

from nomadquant.api.app import create_app
from nomadquant.config import get_settings


def main() -> None:
    try:
        settings = get_settings()
    except (ValidationError, ValueError) as exc:
        sys.stderr.write(f"Configuration error: {exc}\n")
        raise SystemExit(1) from exc
    uvicorn.run(
        create_app(settings),
        host=settings.api_host,
        port=settings.api_port,
        log_config=None,
    )
