"""Budgeted, allow-listed wrapper around the read-only research tools.

Everything here is enforced at runtime. Nothing depends on the model following
instructions: unknown tools, broker tools, raised as_of cutoffs and tool
budgets are all rejected in code.
"""

from __future__ import annotations

import os
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nomadquant.agents.constants import TOOL_SCHEMA_VERSION
from nomadquant.audit import AuditLog
from nomadquant.research.tools import ResearchToolRegistry, ToolError

DEFAULT_MAX_CALLS_PER_RUN = 40
DEFAULT_MAX_CALLS_PER_STAGE = 12
MEMO_TEXT_LIMIT = 8000

FORBIDDEN_TOOLS = frozenset(
    {
        "submit_order",
        "place_order",
        "create_order",
        "cancel_order",
        "cancel_all_orders",
        "replace_order",
        "close_position",
        "close_all_positions",
        "liquidate",
        "transfer",
        "withdraw",
        "get_account",
        "get_positions",
    }
)

# Argument documentation shown to the model. TOOL_SCHEMA_VERSION tracks changes here.
TOOL_SCHEMAS: dict[str, dict[str, str]] = {
    "read_market_data": {
        "symbol": "ticker, e.g. SPY",
        "start": "ISO timestamp with timezone",
        "end": "ISO timestamp with timezone, not after the runtime as_of",
        "feed": "optional, sip or iex",
    },
    "inspect_data_quality": {},
    "read_experiment": {"experiment_id": "registered experiment id"},
    "read_run_card": {"run_id": "the research run under review"},
    "verify_backtest": {"run_id": "the research run under review"},
    "list_research_evidence": {"experiment_id": "optional experiment id"},
    "save_research_memo": {"name": "single .md filename", "text": "memo body, max 8000 chars"},
}
ALLOWED_TOOLS = frozenset(TOOL_SCHEMAS)


class GuardedToolError(ToolError):
    """A tool call was rejected by the guard before any side effect."""


class ToolBudgetExceeded(GuardedToolError):
    """A per-run or per-stage tool call limit was reached."""


@dataclass(frozen=True)
class ToolCallRecord:
    seq: int
    stage: str
    tool: str
    arguments: dict[str, Any]
    status: str  # ok | rejected | error
    result: dict[str, Any] | None
    error: str
    latency_ms: int


Recorder = Callable[[ToolCallRecord], None]


@dataclass
class _StageState:
    name: str = ""
    allowed: frozenset[str] = frozenset()
    calls: int = 0
    called_ok: set[str] = field(default_factory=set)


class GuardedResearchTools:
    def __init__(
        self,
        *,
        market_path: str | Path,
        research_path: str | Path,
        memo_root: str | Path,
        agent_run_id: int,
        as_of: datetime,
        allowed_run_ids: Iterable[int] = (),
        max_calls_per_run: int = DEFAULT_MAX_CALLS_PER_RUN,
        max_calls_per_stage: int = DEFAULT_MAX_CALLS_PER_STAGE,
        audit: AuditLog | None = None,
        recorder: Recorder | None = None,
        initial_calls: int = 0,
    ) -> None:
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware.")
        self._registry = ResearchToolRegistry(
            market_path=market_path, research_path=research_path, memo_root=memo_root
        )
        self.agent_run_id = agent_run_id
        self._as_of = as_of.astimezone(UTC)
        self._allowed_run_ids = frozenset(int(item) for item in allowed_run_ids)
        self.max_calls_per_run = max_calls_per_run
        self.max_calls_per_stage = max_calls_per_stage
        self._audit = audit
        self._recorder = recorder
        self._total_calls = initial_calls
        self._stage = _StageState()
        self._results: dict[str, dict[str, Any]] = {}
        self._memo_dir = (Path(memo_root).resolve() / f"agent-run-{agent_run_id}").resolve()

    @property
    def as_of(self) -> datetime:
        return self._as_of

    @property
    def total_calls(self) -> int:
        return self._total_calls

    @property
    def memo_dir(self) -> Path:
        return self._memo_dir

    def begin_stage(self, name: str, allowed: Iterable[str]) -> None:
        """Reset the per-stage counter and set which tools this stage may call."""
        permitted = frozenset(allowed) & ALLOWED_TOOLS
        self._stage = _StageState(name=name, allowed=permitted)

    def stage_called(self, tool: str) -> bool:
        return tool in self._stage.called_ok

    def last_result(self, tool: str) -> dict[str, Any] | None:
        return self._results.get(tool)

    def allowed_tool_schemas(self) -> dict[str, dict[str, str]]:
        return {name: TOOL_SCHEMAS[name] for name in sorted(self._stage.allowed)}

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run one tool call. Raises ToolError subclasses; every call is recorded."""
        started = time.monotonic()
        self._total_calls += 1
        self._stage.calls += 1
        seq = self._total_calls
        stage = self._stage.name
        safe_args: dict[str, Any] = dict(arguments) if isinstance(arguments, dict) else {}
        try:
            self._admit(name, arguments)
            effective = self._prepare(name, safe_args)
            safe_args = effective
            result = self._dispatch(name, effective)
        except GuardedToolError as exc:
            self._finish(seq, stage, name, safe_args, "rejected", None, str(exc), started)
            raise
        except ToolError as exc:
            self._finish(seq, stage, name, safe_args, "error", None, str(exc), started)
            raise
        except (KeyError, TypeError, ValueError, OSError) as exc:
            message = f"Tool {name} failed: {type(exc).__name__}: {exc}"[:300]
            self._finish(seq, stage, name, safe_args, "error", None, message, started)
            raise ToolError(message) from exc
        self._stage.called_ok.add(name)
        self._results[name] = result
        self._finish(seq, stage, name, safe_args, "ok", result, "", started)
        return result

    # -- guards -------------------------------------------------------------

    def _admit(self, name: object, arguments: object) -> None:
        if not isinstance(name, str) or not name:
            raise GuardedToolError("Tool name must be a non-empty string.")
        if not isinstance(arguments, dict):
            raise GuardedToolError("Tool arguments must be a JSON object.")
        if name in FORBIDDEN_TOOLS or "order" in name.lower():
            raise GuardedToolError(f"Tool {name!r} is forbidden. Agents cannot trade.")
        if name not in ALLOWED_TOOLS:
            raise GuardedToolError(f"Unknown tool {name!r}.")
        if name not in self._stage.allowed:
            raise GuardedToolError(f"Tool {name!r} is not permitted in stage {self._stage.name!r}.")
        if self._total_calls > self.max_calls_per_run:
            raise ToolBudgetExceeded(
                f"Run tool budget of {self.max_calls_per_run} calls is exhausted."
            )
        if self._stage.calls > self.max_calls_per_stage:
            raise ToolBudgetExceeded(
                f"Stage tool budget of {self.max_calls_per_stage} calls is exhausted."
            )

    def _prepare(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        prepared = dict(arguments)
        if name == "read_market_data":
            requested = prepared.get("as_of")
            if requested is not None:
                try:
                    parsed = datetime.fromisoformat(str(requested))
                except ValueError as exc:
                    raise GuardedToolError("as_of is not a valid ISO timestamp.") from exc
                if parsed.tzinfo is None:
                    raise GuardedToolError("as_of must include a timezone.")
                if parsed.astimezone(UTC) > self._as_of:
                    raise GuardedToolError("as_of cannot be later than the runtime cutoff.")
                effective = min(parsed.astimezone(UTC), self._as_of)
            else:
                effective = self._as_of
            prepared["as_of"] = effective.isoformat()
            prepared.setdefault("end", effective.isoformat())
        if name in {"read_run_card", "verify_backtest"}:
            if "run_id" not in prepared and len(self._allowed_run_ids) == 1:
                prepared["run_id"] = next(iter(self._allowed_run_ids))
            try:
                run_id = int(prepared["run_id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise GuardedToolError("run_id is required and must be an integer.") from exc
            if self._allowed_run_ids and run_id not in self._allowed_run_ids:
                raise GuardedToolError(f"run_id {run_id} is outside the run under review.")
            prepared["run_id"] = run_id
        return prepared

    def _dispatch(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "save_research_memo":
            return self._save_memo(arguments)
        return self._registry.call(name, arguments)

    def _save_memo(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Atomic write into memo_root/agent-run-{id}/. Text is data and never executed."""
        raw_name = str(arguments["name"])
        name = Path(raw_name).name
        if name != raw_name or not name.endswith(".md") or name.startswith("."):
            raise GuardedToolError("Memo name must be a single .md filename.")
        text = str(arguments["text"])[:MEMO_TEXT_LIMIT]
        self._memo_dir.mkdir(parents=True, exist_ok=True)
        target = (self._memo_dir / name).resolve()
        if target.parent != self._memo_dir:
            raise GuardedToolError("Memo path is outside the agent run directory.")
        handle, temp_name = tempfile.mkstemp(dir=self._memo_dir, prefix=".memo-", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, target)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
        return {
            "path": f"agent-run-{self.agent_run_id}/{name}",
            "bytes": len(text.encode("utf-8")),
        }

    # -- audit --------------------------------------------------------------

    def _finish(
        self,
        seq: int,
        stage: str,
        tool: str,
        arguments: dict[str, Any],
        status: str,
        result: dict[str, Any] | None,
        error: str,
        started: float,
    ) -> None:
        latency = int((time.monotonic() - started) * 1000)
        record = ToolCallRecord(
            seq=seq,
            stage=stage,
            tool=tool,
            arguments=_loggable(arguments),
            status=status,
            result=result,
            error=error,
            latency_ms=latency,
        )
        if self._recorder is not None:
            self._recorder(record)
        if self._audit is not None:
            self._audit.record_event(
                event_type="agent.tool_call",
                event_level="info" if status == "ok" else "warning",
                component="agent",
                status={"ok": "succeeded", "rejected": "warning", "error": "failed"}[status],
                title=f"Agent tool call {tool}",
                summary=f"{status}: {tool} in stage {stage}. {error}"[:500],
                correlation_id=f"agent-run-{self.agent_run_id}",
                payload={
                    "agent_run_id": self.agent_run_id,
                    "seq": seq,
                    "stage": stage,
                    "tool": tool,
                    "status": status,
                    "arguments": record.arguments,
                    "tool_schema_version": TOOL_SCHEMA_VERSION,
                    "latency_ms": latency,
                },
                error_code="" if status == "ok" else status,
                error_message_safe=error[:500],
            )


def _loggable(arguments: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in arguments.items():
        if key == "text" and isinstance(value, str):
            out[key] = f"<{len(value)} chars>"
        else:
            out[str(key)[:100]] = (
                value if isinstance(value, int | float | bool) else str(value)[:300]
            )
    return out
