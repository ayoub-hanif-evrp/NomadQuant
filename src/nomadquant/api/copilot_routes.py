"""Local copilot. POST asks a question. It cannot place an order."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from nomadquant.api.csrf import require_local_mutation
from nomadquant.copilot.service import answer_question

router = APIRouter(prefix="/api/copilot")


class Turn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=2000)


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    history: list[Turn] = Field(default_factory=list, max_length=12)


@router.post("/ask")
def ask(body: AskBody, request: Request) -> dict[str, Any]:
    require_local_mutation(request)
    try:
        return answer_question(
            request.app.state.settings,
            body.question,
            history=[turn.model_dump() for turn in body.history],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
