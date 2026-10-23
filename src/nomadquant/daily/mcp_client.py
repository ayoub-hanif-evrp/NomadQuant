"""Call the daily MCP server through the official client session."""

from __future__ import annotations

from typing import Any

from nomadquant.daily.mcp_server import MarketContext, build_server
from nomadquant.daily.tool_registry import ALLOWED_TOOLS
from nomadquant.daily.tool_registry import FORBIDDEN_CAPABILITIES as FORBIDDEN_TOOLS

MAX_CALLS = 12
DEFAULT_TOOLS = ("eligible_signals", "indicator_snapshot", "sleeve_snapshot")


def selected_names(requested: list[str] | None) -> list[str]:
    """Keep only approved read-only tools. Broker-control names are dropped."""
    if not requested:
        return list(DEFAULT_TOOLS)
    chosen: list[str] = []
    for name in requested:
        if name in ALLOWED_TOOLS and name not in chosen:
            chosen.append(name)
        if len(chosen) >= MAX_CALLS:
            break
    return chosen or list(DEFAULT_TOOLS)


def invoke_readonly_tools(
    context: MarketContext,
    as_of: str,
    *,
    requested: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Discover tools, then call only the approved names an agent selected."""
    import anyio

    async def _run() -> list[dict[str, Any]]:
        from mcp.client._memory import InMemoryTransport
        from mcp.client.session import ClientSession

        server = build_server(context)
        async with InMemoryTransport(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                return await _collect(session, as_of, selected_names(requested))

    return anyio.run(_run)


async def _collect(session: Any, as_of: str, names_to_call: list[str]) -> list[dict[str, Any]]:
    listed = await session.list_tools()
    names = [tool.name for tool in listed.tools]
    if any(name in FORBIDDEN_TOOLS for name in names):
        raise RuntimeError("A broker-control tool was exposed.")
    if len(names_to_call) > MAX_CALLS:
        raise RuntimeError("Tool budget exceeded.")
    results: list[dict[str, Any]] = []
    for name in names_to_call:
        arguments = (
            {}
            if name in {"strategy_registry", "sleeve_snapshot"}
            else {"symbol": "SPY", "as_of": as_of}
        )
        if name == "eligible_signals":
            arguments = {"as_of": as_of}
        response = await session.call_tool(name, arguments)
        results.append({"tool": name, "is_error": bool(response.is_error), "text": _text(response)})
    return results


def _text(response: Any) -> str:
    chunks: list[str] = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            chunks.append(str(text)[:4000])
    return "\n".join(chunks)
