"""Local copilot. POST asks a question. It cannot place an order."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from nomadquant.api.csrf import require_local_mutation
from nomadquant.copilot.service import answer_question

router = APIRouter(prefix="/api/copilot")


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=500)


@router.post("/ask")
def ask(body: AskBody, request: Request) -> dict[str, Any]:
    require_local_mutation(request)
    try:
        return answer_question(request.app.state.settings, body.question)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
