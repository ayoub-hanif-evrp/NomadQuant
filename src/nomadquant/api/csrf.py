"""Localhost mutation check. A cross-site page cannot set this header."""

from fastapi import HTTPException, Request

_ORIGINS = frozenset({"http://127.0.0.1:3000", "http://localhost:3000"})
_INTENT = "mutate"


def require_local_mutation(request: Request) -> None:
    origin = request.headers.get("origin", "")
    intent = request.headers.get("x-nomadquant-intent", "")
    if origin not in _ORIGINS or intent != _INTENT:
        raise HTTPException(
            status_code=403,
            detail="This action is only accepted from the local NomadQuant dashboard.",
        )
