"""Audited read-only tool list. Names absent from this registry are not callable."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str
    classification: str
    timeout_seconds: int
    max_response_chars: int
    cache_seconds: int
    source: str


FORBIDDEN_CAPABILITIES = frozenset(
    {
        "submit_order",
        "cancel_order",
        "replace_order",
        "withdraw",
        "close_position",
        "get_account",
        "authorize",
        "change_risk_policy",
        "write_position",
    }
)

TOOLS = (
    ToolSpec("strategy_registry", "1", "read_only", 5, 4000, 3600, "local_registry"),
    ToolSpec("eligible_signals", "1", "read_only", 5, 4000, 0, "local_prices"),
    ToolSpec("indicator_snapshot", "1", "read_only", 5, 4000, 0, "local_prices"),
    ToolSpec("quote_snapshot", "1", "read_only", 5, 4000, 0, "caller_context"),
    ToolSpec("news_headlines", "1", "read_only", 5, 4000, 0, "caller_context"),
    ToolSpec("sleeve_snapshot", "1", "read_only", 5, 4000, 0, "local_sleeve"),
)

ALLOWED_TOOLS = frozenset(tool.name for tool in TOOLS if tool.classification == "read_only")


def public_tools() -> list[dict[str, str | int]]:
    return [
        {
            "name": tool.name,
            "version": tool.version,
            "classification": tool.classification,
            "timeout_seconds": tool.timeout_seconds,
            "max_response_chars": tool.max_response_chars,
            "cache_seconds": tool.cache_seconds,
            "source": tool.source,
            "mutating": False,
        }
        for tool in TOOLS
    ]
