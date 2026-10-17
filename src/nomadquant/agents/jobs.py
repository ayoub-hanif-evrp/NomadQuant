"""Web-started research reviews.

A job row is persisted before the caller is told anything started, the worker
uses the same Ollama provider as the CLI, and every outcome (including a crash)
is written back. Only one model job runs at a time.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Protocol

from nomadquant.agents.ollama import OllamaError
from nomadquant.agents.store import AgentStore, AgentStoreError
from nomadquant.agents.workflow import ChatProvider, live_market_digest, run_research_review
from nomadquant.audit import AuditLog
from nomadquant.config import Settings
from nomadquant.logging import get_logger
from nomadquant.research.store import ResearchStore

logger = get_logger(__name__)

_WORKER_LOCK = threading.Lock()


class ReviewProvider(ChatProvider, Protocol):
    def health(self, timeout: float = 2.0) -> dict[str, Any]: ...


class ReviewRefused(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def start_review_job(
    settings: Settings,
    provider: ReviewProvider,
    *,
    research_run_id: int,
    model: str,
    background: bool = True,
) -> dict[str, Any]:
    """Check every precondition, persist a queued job, then start the worker."""
    health = provider.health()
    if not health.get("available"):
        raise ReviewRefused(503, "Local AI (Ollama) is not running, so no review was started.")
    if model not in set(health.get("models") or []):
        raise ReviewRefused(409, "That model is not installed. No download was started.")

    research_path = Path(settings.research_path)
    run = ResearchStore(research_path).get_run(research_run_id) if research_path.exists() else None
    if run is None:
        raise ReviewRefused(404, f"Research run {research_run_id} was not found.")
    if run["status"] != "succeeded":
        raise ReviewRefused(
            409, f"Research run {research_run_id} has status {run['status']!r}, not 'succeeded'."
        )
    recorded = str(run["dataset_fingerprint"])
    live = live_market_digest(run, settings.market_data_path)
    if not live or live != recorded:
        raise ReviewRefused(
            409,
            "The stored market data no longer matches what this research run used, "
            "so its numbers cannot be checked. Re-run the research first.",
        )

    model_digest = ""
    digest_fn = getattr(provider, "model_digest", None)
    if callable(digest_fn):
        try:
            model_digest = str(digest_fn(model) or "")
        except OllamaError:
            model_digest = ""

    if not _WORKER_LOCK.acquire(blocking=False):
        raise ReviewRefused(409, "A local review is already running.")
    try:
        store = AgentStore(settings.agents_path)
        job = store.create_job(
            research_run_id=research_run_id,
            model=model,
            model_digest=model_digest,
            dataset_fingerprint=recorded,
        )
    except AgentStoreError as exc:
        _WORKER_LOCK.release()
        raise ReviewRefused(409, str(exc)) from exc
    except BaseException:
        _WORKER_LOCK.release()
        raise

    job_id = int(job["id"])
    if background:
        threading.Thread(
            target=_run_job,
            args=(settings, provider, job_id, research_run_id, model),
            name=f"nomadquant-review-{job_id}",
            daemon=True,
        ).start()
    else:
        _run_job(settings, provider, job_id, research_run_id, model)
    refreshed = store.get_job(job_id)
    assert refreshed is not None
    return refreshed


def _run_job(
    settings: Settings,
    provider: ChatProvider,
    job_id: int,
    research_run_id: int,
    model: str,
) -> None:
    store = AgentStore(settings.agents_path)
    created: dict[str, int] = {}

    def on_run_created(agent_run_id: int) -> None:
        created["id"] = agent_run_id
        store.attach_job_run(job_id, agent_run_id)

    try:
        store.mark_job_running(job_id)
        detail = run_research_review(
            research_run_id,
            model,
            research_path=settings.research_path,
            market_path=settings.market_data_path,
            memo_root=settings.agent_memo_root,
            store=store,
            provider=provider,
            audit=AuditLog(settings.database_path, settings.secret_values),
            on_run_created=on_run_created,
        )
        ok = detail["status"] == "succeeded"
        store.finish_job(
            job_id,
            status="succeeded" if ok else "failed",
            error_code="" if ok else str(detail.get("error_code") or "review_failed"),
            error_message_safe="" if ok else str(detail.get("error_message_safe") or ""),
        )
    except Exception as exc:
        logger.exception("review_job_crashed job_id=%s", job_id)
        message = f"{type(exc).__name__}: {exc}"[:500]
        agent_run_id = created.get("id")
        if agent_run_id is not None:
            store.fail_open_stages(
                agent_run_id, error_code=type(exc).__name__, error_message_safe=message
            )
            run = store.get_run(agent_run_id)
            if run is not None and run["status"] == "running":
                store.finish_run(
                    agent_run_id,
                    status="failed",
                    summary="Review crashed.",
                    error_code=type(exc).__name__,
                    error_message_safe=message,
                )
        store.finish_job(
            job_id, status="failed", error_code=type(exc).__name__, error_message_safe=message
        )
    finally:
        _WORKER_LOCK.release()
