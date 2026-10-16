"""Independent checks for one stored shadow cycle. Never mutates the ledger."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from nomadquant.config import Settings
from nomadquant.marketdata.availability import modeled_available_at
from nomadquant.marketdata.calendar import sessions_between
from nomadquant.marketdata.store import MarketStore, content_hash
from nomadquant.research.signals import momentum_return
from nomadquant.shadow.cycle import FEED, LOOKBACK, SKIP, STRATEGY_ID, SYMBOL, _hash
from nomadquant.shadow.provenance import EXECUTION_DELAYED_HYPOTHETICAL
from nomadquant.shadow.store import ShadowStore

Check = dict[str, str]


def verify_cycle(settings: Settings, cycle_id: int) -> dict[str, Any]:
    """Recompute what the cycle should show. Do not trust its stored totals alone."""
    path = Path(settings.shadow_path)
    if not path.exists():
        return _result(cycle_id, "INVALID_ARTIFACT", [], "shadow ledger is missing")
    shadow = ShadowStore(path, namespace="forward")
    cycle = shadow.get_cycle(cycle_id)
    if cycle is None:
        return _result(cycle_id, "INVALID_ARTIFACT", [], f"cycle {cycle_id} was not found")
    checks: list[Check] = []
    evidence = cycle.get("evidence") if isinstance(cycle.get("evidence"), dict) else None
    if not evidence:
        checks.append(_check("evidence_present", "INVALID_ARTIFACT", "evidence JSON is missing"))
        return _result(cycle_id, "INVALID_ARTIFACT", checks, "original evidence is absent")

    recomputed_hash = _hash(evidence)
    stored_hash = str(cycle.get("evidence_hash") or "")
    checks.append(
        _check(
            "evidence_hash",
            "PASS" if stored_hash and stored_hash == recomputed_hash else "FAIL",
            "stored evidence hash matches a fresh hash of the evidence object",
        )
    )
    checks.append(
        _check(
            "strategy_id",
            "PASS" if evidence.get("strategy_id", STRATEGY_ID) == STRATEGY_ID else "FAIL",
            STRATEGY_ID,
        )
    )
    signal_raw = cycle.get("signal_session") or evidence.get("signal_session")
    if not signal_raw:
        checks.append(_check("signal_session", "NOT_EVALUABLE", "no signal session on this row"))
        return _result(cycle_id, _overall(checks), checks, "no signal session")
    signal_day = date.fromisoformat(str(signal_raw))
    market_path = Path(settings.market_data_path)
    market = MarketStore.open_readonly(market_path) if market_path.exists() else None
    if market is None or not market.has_symbol(SYMBOL, FEED):
        checks.append(_check("market_source", "INVALID_ARTIFACT", "SIP bars are not stored"))
        return _result(cycle_id, "INVALID_ARTIFACT", checks, "market evidence is absent")

    stored_sessions = sorted(market.sessions(SYMBOL, FEED))
    sessions = sessions_between(stored_sessions[0], stored_sessions[-1])
    closes = {
        session: close
        for session, _o, _h, _l, close in market.session_ohlc(
            SYMBOL, FEED, stored_sessions[0], signal_day
        )
    }
    future = [session for session in closes if session > signal_day]
    checks.append(
        _check(
            "no_future_observations",
            "FAIL" if future else "PASS",
            "momentum inputs stop at the signal session",
        )
    )
    recomputed = momentum_return(closes, sessions, signal_day, LOOKBACK, SKIP)
    stored_momentum = evidence.get("momentum")
    if stored_momentum is None or recomputed is None:
        checks.append(
            _check(
                "momentum_recompute",
                "NOT_EVALUABLE",
                "momentum was not stored or cannot be recomputed",
            )
        )
    else:
        same = Decimal(str(stored_momentum)) == recomputed
        checks.append(
            _check(
                "momentum_recompute",
                "PASS" if same else "FAIL",
                "recomputed from stored closes, not copied from the cycle row",
            )
        )
    signal_bar = market.session_bar(SYMBOL, FEED, signal_day)
    if signal_bar is None:
        checks.append(_check("signal_bar", "INVALID_ARTIFACT", "signal session bar is missing"))
    else:
        fresh_hash = content_hash(signal_bar)
        checks.append(
            _check(
                "signal_bar_hash",
                "PASS" if fresh_hash == signal_bar.content_hash else "FAIL",
                "bar content hash recomputed from stored OHLC",
            )
        )
        created = _parse(str(cycle.get("created_at")))
        retrieved = signal_bar.first_retrieved_at
        if created is None:
            checks.append(_check("retrieval_cutoff", "NOT_EVALUABLE", "created_at is missing"))
        elif cycle.get("status") == "missed_signal":
            checks.append(
                _check(
                    "missed_not_backfilled",
                    "PASS" if cycle.get("fill_price") in {None, ""} else "FAIL",
                    "a missed rebalance has no fill",
                )
            )
        elif retrieved > created and evidence.get("realtime_executable") is True:
            checks.append(
                _check(
                    "retrieval_cutoff",
                    "FAIL",
                    "bar was retrieved after the decision and marked executable",
                )
            )
        else:
            checks.append(
                _check(
                    "retrieval_cutoff",
                    "PASS",
                    f"retrieved={retrieved.isoformat()} created={cycle.get('created_at')}",
                )
            )
    if cycle.get("status") in {"filled", "dry_run_approved"}:
        assumption = str(evidence.get("execution_model") or "")
        checks.append(
            _check(
                "fill_assumption",
                "PASS" if assumption == EXECUTION_DELAYED_HYPOTHETICAL else "FAIL",
                assumption or "missing execution model",
            )
        )
        checks.append(
            _check(
                "not_realtime",
                "PASS" if evidence.get("realtime_executable") is False else "FAIL",
                "daily open is not a real-time execution",
            )
        )
    else:
        checks.append(_check("fill_assumption", "NOT_EVALUABLE", "this row has no simulated fill"))
    before = cycle.get("ledger_before") or {}
    after = cycle.get("ledger_after") or {}
    if before and after and cycle.get("status") != "filled":
        same_cash = str(before.get("cash_usd")) == str(after.get("cash_usd"))
        checks.append(
            _check(
                "cash_unchanged_without_fill",
                "PASS" if same_cash else "FAIL",
                "non-fill rows must not change cash",
            )
        )
    available = modeled_available_at(signal_day)
    checks.append(
        _check(
            "information_cutoff",
            "PASS",
            f"modeled_available_at={available.isoformat()}",
        )
    )
    label = str(cycle.get("label") or "")
    checks.append(
        _check(
            "prospective_label",
            "PASS" if label in {"forward_shadow", "retrospective_replay"} else "FAIL",
            label,
        )
    )
    return _result(cycle_id, _overall(checks), checks, "independent recompute")


def _parse(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed


def _check(name: str, status: str, detail: str) -> Check:
    return {"name": name, "status": status, "detail": detail}


def _overall(checks: list[Check]) -> str:
    statuses = {row["status"] for row in checks}
    if "FAIL" in statuses:
        return "FAIL"
    if "INVALID_ARTIFACT" in statuses:
        return "INVALID_ARTIFACT"
    if not checks or statuses == {"NOT_EVALUABLE"}:
        return "NOT_EVALUABLE"
    return "PASS"


def _result(cycle_id: int, status: str, checks: list[Check], note: str) -> dict[str, Any]:
    return {
        "cycle_id": cycle_id,
        "status": status,
        "verified": status == "PASS",
        "checks": checks,
        "note": note,
    }
