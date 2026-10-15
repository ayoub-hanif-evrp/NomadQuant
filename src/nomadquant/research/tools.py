"""Read-only research tools for a future local agent. No broker methods."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from nomadquant.marketdata.provider import SqliteMarketDataProvider
from nomadquant.marketdata.report import market_data_status
from nomadquant.marketdata.store import MarketStore
from nomadquant.research.store import ResearchStore
from nomadquant.research.verify import verify_run

MEMO_NAME = "research-memos"


class ToolError(ValueError):
    """A tool call was rejected before any side effect."""


class ResearchToolRegistry:
    def __init__(
        self,
        *,
        market_path: str | Path,
        research_path: str | Path,
        memo_root: str | Path,
    ) -> None:
        self.market_path = Path(market_path)
        self.research_path = Path(research_path)
        self.memo_root = Path(memo_root).resolve()
        self.memo_root.mkdir(parents=True, exist_ok=True)

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = {
            "read_market_data": self.read_market_data,
            "inspect_data_quality": self.inspect_data_quality,
            "read_experiment": self.read_experiment,
            "read_run_card": self.read_run_card,
            "verify_backtest": self.verify_backtest,
            "list_research_evidence": self.list_research_evidence,
            "save_research_memo": self.save_research_memo,
        }.get(name)
        if handler is None:
            raise ToolError(f"Unknown tool {name}.")
        if name in {"submit_order", "cancel_order", "close_position"}:
            raise ToolError("Broker tools are not available.")
        return handler(arguments)

    def read_market_data(self, arguments: dict[str, Any]) -> dict[str, Any]:
        symbol = str(arguments["symbol"])
        feed = str(arguments.get("feed", "sip"))
        as_of = _aware(str(arguments["as_of"]))
        start = _aware(str(arguments["start"]))
        end = _aware(str(arguments["end"]))
        if end > as_of:
            raise ToolError("Requested end is after the as_of cutoff.")
        provider = SqliteMarketDataProvider(MarketStore(self.market_path), feed)
        bars = provider.get_bars([symbol], start, end, as_of)
        limited = bars[:200]
        return {
            "symbol": symbol,
            "as_of": as_of.isoformat(),
            "returned": len(limited),
            "truncated": len(bars) > len(limited),
            "bars": [
                {
                    "session_date": bar.session_date.isoformat(),
                    "close": str(bar.close),
                    "available_at": bar.as_of.isoformat(),
                }
                for bar in limited
            ],
        }

    def inspect_data_quality(self, arguments: dict[str, Any]) -> dict[str, Any]:
        status = market_data_status(str(self.market_path))
        return {"suitable_for_research": status.suitable_for_research, "caveat": status.caveat}

    def read_experiment(self, arguments: dict[str, Any]) -> dict[str, Any]:
        item = ResearchStore(self.research_path).get_experiment(str(arguments["experiment_id"]))
        if item is None:
            raise ToolError("Experiment not found.")
        return item

    def read_run_card(self, arguments: dict[str, Any]) -> dict[str, Any]:
        card = ResearchStore(self.research_path).get_run_card(int(arguments["run_id"]))
        if card is None:
            raise ToolError("Run card not found.")
        return card

    def verify_backtest(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return verify_run(
            int(arguments["run_id"]),
            research_path=self.research_path,
            market_path=self.market_path,
        )

    def list_research_evidence(self, arguments: dict[str, Any]) -> dict[str, Any]:
        runs = ResearchStore(self.research_path).list_runs(arguments.get("experiment_id"))
        return {"items": runs[:50], "truncated": len(runs) > 50}

    def save_research_memo(self, arguments: dict[str, Any]) -> dict[str, Any]:
        name = Path(str(arguments["name"])).name
        if name != arguments["name"] or not name.endswith(".md"):
            raise ToolError("Memo name must be a single .md filename.")
        target = (self.memo_root / name).resolve()
        if self.memo_root not in target.parents and target != self.memo_root / name:
            raise ToolError("Memo path is outside the research workspace.")
        text = str(arguments["text"])[:8000]
        target.write_text(text, encoding="utf-8")
        return {"path": name, "bytes": len(text.encode("utf-8"))}


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ToolError("Timestamps must include a timezone.")
    return parsed
