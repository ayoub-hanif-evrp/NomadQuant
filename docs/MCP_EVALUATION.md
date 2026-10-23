# MCP evaluation

These projects were checked as published sources. None of them is installed for NomadQuant agents. Publication on GitHub is not a reason to connect a tool that can trade or read credentials.

| Source | Decision |
| --- | --- |
| Alpaca MCP server | Rejected for agents. Its toolset can place orders and can be pointed at live trading. A paper research allowlist was not activated. The broker adapter remains the only submission path. |
| Playwright MCP | Deferred. The web package already depends on Playwright. It is not connected to the trading decision. |
| GitHub MCP | Deferred. Useful for development review, not for a paper order. |
| MCP reference servers | Rejected for production. Filesystem and git access need a separate review. |
| Financial Datasets MCP | Deferred. Subscription and license were not verified. |
| FRED API | Deferred. No adapter is implemented. A later adapter would be read-only and would keep vintage timestamps. |
| SEC EDGAR APIs | Deferred. No adapter is implemented. Fair-access limits would apply. |

The agent surface remains `nomadquant-daily-readonly`. Its names, timeouts, and size limits are in `daily/tool_registry.py`. Forbidden names include order, cancel, withdraw, authorization, and risk-policy changes. Tool text is untrusted data.

Deterministic signals do not call an external MCP server.
