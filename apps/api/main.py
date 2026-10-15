"""Thin ASGI entrypoint for ``uvicorn apps.api.main:app``."""

from nomadquant.api.app import create_app

app = create_app()
