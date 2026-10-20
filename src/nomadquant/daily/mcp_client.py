"""Call the daily MCP server through the official client session."""

from __future__ import annotations

from typing import Any

from nomadquant.daily.mcp_server import FORBIDDEN_TOOLS, MarketContext, build_server

MAX_CALLS = 12


def invoke_readonly_tools(context: MarketContext, as_of: str) -> list[dict[str, Any]]:
    """Discover tools, reject broker-control names, then call the read-only set."""
    import anyio

    async def _run() -> list[dict[str, Any]]:
        from mcp.client._memory import InMemoryTransport
        from mcp.client.session import ClientSession

        server = build_server(context)
        async with InMemoryTransport(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                return await _collect(session, as_of)

    return anyio.run(_run)


async def _collect(session: Any, as_of: str) -> list[dict[str, Any]]:
    listed = await session.list_tools()
    names = [tool.name for tool in listed.tools]
    if any(name in FORBIDDEN_TOOLS for name in names):
        raise RuntimeError("A broker-control tool was exposed.")
    calls = [
        ("strategy_registry", {}),
        ("eligible_signals", {"as_of": as_of}),
        ("indicator_snapshot", {"symbol": "SPY", "as_of": as_of}),
        ("quote_snapshot", {"symbol": "SPY", "as_of": as_of}),
        ("news_headlines", {"symbol": "SPY", "as_of": as_of}),
        ("sleeve_snapshot", {}),
    ]
    if len(calls) > MAX_CALLS:
        raise RuntimeError("Tool budget exceeded.")
    results: list[dict[str, Any]] = []
    for name, arguments in calls:
        response = await session.call_tool(name, arguments)
        results.append(
            {
                "tool": name,
                "is_error": bool(response.is_error),
                "text": _text(response),
            }
        )
    try:
        refused = await session.call_tool("submit_order", {})
        results.append({"tool": "submit_order", "is_error": True, "text": _text(refused)})
    except Exception as exc:  # noqa: BLE001 — a missing tool must not become a broker call
        results.append({"tool": "submit_order", "is_error": True, "text": type(exc).__name__})
    return results


def _text(response: Any) -> str:
    chunks: list[str] = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            chunks.append(str(text)[:4000])
    return "\n".join(chunks)
