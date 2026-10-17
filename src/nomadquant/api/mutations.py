"""Explicit localhost mutations. None of these submit a broker order."""

from __future__ import annotations

POST_ROUTES = frozenset(
    {
        "/api/approvals/{request_id}/decide",
        "/api/copilot/ask",
        "/api/news/refresh",
        "/api/news/analyze",
        "/api/market-data/sync",
        "/api/agents/reviews",
    }
)

_WRITES = frozenset({"post", "put", "patch", "delete"})


def assert_route_safety(paths: dict[str, dict[str, object]]) -> None:
    """GET stays read-only. POST is an allowlist. No order routes."""
    for path, operations in paths.items():
        lowered = path.lower()
        if "order" in lowered:
            raise AssertionError(path)
        methods = {name for name in operations if name in {"get", "post", "put", "patch", "delete"}}
        if methods & {"put", "patch", "delete"}:
            raise AssertionError(path)
        if "post" in methods:
            if path not in POST_ROUTES:
                raise AssertionError(path)
            if "get" in methods:
                raise AssertionError(path)
        elif methods != {"get"}:
            raise AssertionError(path)
