"""Headline routes. GET does not call Alpaca. Refresh and analysis are explicit."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from nomadquant.api.csrf import require_local_mutation
from nomadquant.news.service import analyze_headline, news_view, refresh_news

router = APIRouter(prefix="/api/news")


class AnalyzeBody(BaseModel):
    article_id: str = Field(min_length=1, max_length=80)


@router.get("/headlines")
def list_news(request: Request) -> dict[str, Any]:
    return news_view(request.app.state.settings)


@router.post("/refresh")
def refresh(request: Request) -> dict[str, Any]:
    require_local_mutation(request)
    return refresh_news(request.app.state.settings)


@router.post("/analyze")
def analyze(body: AnalyzeBody, request: Request) -> dict[str, Any]:
    require_local_mutation(request)
    try:
        return analyze_headline(request.app.state.settings, body.article_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
