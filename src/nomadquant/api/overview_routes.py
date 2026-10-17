"""One read-only summary for the home screen."""

from typing import Any

from fastapi import APIRouter, Request

from nomadquant.overview import overview

router = APIRouter(prefix="/api")


@router.get("/overview")
def product_overview(request: Request) -> dict[str, Any]:
    return overview(request.app.state.settings)
