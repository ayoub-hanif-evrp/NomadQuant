"""Independent checks for one stored shadow cycle. Never mutates the ledger."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from nomadquant.config import Settings
from nomadquant.finance.accounting import Book, apply_fill
from nomadquant.finance.execution import (
    CONVENTION_ID,
    LEGACY_SHADOW_CONVENTION_ID,
    execution_price,
    legacy_shadow_execution_price,
)
from nomadquant.marketdata.availability import modeled_available_at
from nomadquant.marketdata.calendar import sessions_between
from nomadquant.marketdata.store import MarketStore, content_hash
from nomadquant.research.models import CostModel
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
        return _result(cycle_id, "NOT_EVALUABLE", checks, "no signal session")
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
    if cycle.get("status") == "missed_signal" and not stored_momentum:
        checks.append(
            _check(
                "momentum_recompute",
                "NOT_APPLICABLE",
                "a missed cycle did not record a signal to recompute",
            )
        )
    elif stored_momentum is None or recomputed is None:
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
    filled = cycle.get("status") in {"filled", "dry_run_approved"}
    if filled:
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
        checks.append(
            _check(
                "fill_assumption",
                "NOT_APPLICABLE",
                "no simulated fill occurred, so fill verification is out of scope",
            )
        )
    before = cycle.get("ledger_before") or {}
    after = cycle.get("ledger_after") or {}
    if cycle.get("status") == "filled":
        checks.extend(_recompute_fill(cycle, evidence, market))
    elif before and after:
        same_cash = str(before.get("cash_usd")) == str(after.get("cash_usd"))
        checks.append(
            _check(
                "cash_unchanged_without_fill",
                "PASS" if same_cash else "FAIL",
                "non-fill rows must not change cash",
            )
        )
    available = modeled_available_at(signal_day)
    checks.append(_information_cutoff(evidence, cycle, available))
    label = str(cycle.get("label") or "")
    checks.append(
        _check(
            "prospective_label",
            "PASS" if label in {"forward_shadow", "retrospective_replay"} else "FAIL",
            label,
        )
    )
    scopes = _scopes(checks)
    return _result(cycle_id, scopes["full_cycle"], checks, "independent recompute", scopes)


def _parse(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed


def _check(name: str, status: str, detail: str) -> Check:
    return {"name": name, "status": status, "detail": detail}


def _information_cutoff(
    evidence: dict[str, Any], cycle: dict[str, Any], available: datetime
) -> Check:
    raw = evidence.get("signal_available_at") or evidence.get("information_cutoff")
    if not raw:
        return _check(
            "information_cutoff",
            "NOT_EVALUABLE",
            "the original allowable cutoff was not stored",
        )
    parsed = _parse(str(raw))
    if parsed is None:
        return _check("information_cutoff", "INVALID_ARTIFACT", "cutoff timestamp did not parse")
    if parsed != available:
        return _check(
            "information_cutoff",
            "FAIL",
            f"stored {parsed.isoformat()} modeled {available.isoformat()}",
        )
    created = _parse(str(cycle.get("created_at") or ""))
    if created is not None and created < available and cycle.get("label") == "forward_shadow":
        return _check(
            "information_cutoff",
            "FAIL",
            "forward row was created before the signal was available",
        )
    return _check("information_cutoff", "PASS", f"cutoff matches {available.isoformat()}")


def _recompute_fill(
    cycle: dict[str, Any],
    evidence: dict[str, Any],
    market: MarketStore,
) -> list[Check]:
    fill_raw = cycle.get("fill_session")
    qty_raw = cycle.get("fill_qty")
    side = cycle.get("fill_side")
    stored_price = cycle.get("fill_price")
    if not fill_raw or not qty_raw or side not in {"buy", "sell"} or not stored_price:
        return [_check("fill_recompute", "NOT_EVALUABLE", "fill quantity or session is absent")]
    bar = market.session_bar(SYMBOL, FEED, date.fromisoformat(str(fill_raw)))
    if bar is None:
        return [_check("fill_recompute", "INVALID_ARTIFACT", "fill-session bar is missing")]
    convention = str(evidence.get("execution_convention") or "")
    costs = CostModel()
    if convention == CONVENTION_ID:
        expected = execution_price(bar.open, costs, side=side)
    elif convention == LEGACY_SHADOW_CONVENTION_ID:
        expected = legacy_shadow_execution_price(bar.open, costs, side=side)
    else:
        return [
            _check(
                "fill_recompute",
                "NOT_EVALUABLE",
                "execution convention was not recorded on this cycle",
            )
        ]
    price_ok = Decimal(str(stored_price)) == expected
    checks = [
        _check(
            "fill_recompute",
            "PASS" if price_ok else "FAIL",
            f"recomputed {expected} from the stored open using {convention}",
        )
    ]
    before = cycle.get("ledger_before") or {}
    after = cycle.get("ledger_after") or {}
    if not before or not after:
        checks.append(_check("ledger_recompute", "NOT_EVALUABLE", "ledger snapshots are absent"))
        return checks
    try:
        book = Book(
            cash=Decimal(str(before["cash_usd"])),
            holdings={k: Decimal(str(v)) for k, v in dict(before.get("holdings") or {}).items()},
            cost_basis={
                k: Decimal(str(v)) for k, v in dict(before.get("cost_basis") or {}).items()
            },
            realized_pnl=Decimal(str(before.get("realized_pnl_usd") or "0")),
            attributed_costs=Decimal(str(before.get("total_costs_usd") or "0")),
        )
        updated, _result_fill = apply_fill(
            book,
            symbol=SYMBOL,
            side=side,
            quantity=Decimal(str(qty_raw)),
            mid=bar.open,
            costs=costs,
        )
    except (ValueError, KeyError) as exc:
        checks.append(_check("ledger_recompute", "FAIL", type(exc).__name__))
        return checks
    if convention != CONVENTION_ID:
        checks.append(
            _check(
                "ledger_recompute",
                "NOT_EVALUABLE",
                "legacy convention is recognized but not replayed as the current kernel",
            )
        )
        return checks
    same = updated.cash == Decimal(str(after.get("cash_usd"))) and {
        k: str(v) for k, v in updated.holdings.items()
    } == {k: str(v) for k, v in dict(after.get("holdings") or {}).items()}
    checks.append(
        _check(
            "ledger_recompute",
            "PASS" if same else "FAIL",
            "cash and holdings recomputed from the pre-fill ledger",
        )
    )
    return checks


def _scopes(checks: list[Check]) -> dict[str, str]:
    groups = {
        "evidence_integrity": {"evidence_hash", "strategy_id", "prospective_label"},
        "signal_recomputation": {
            "momentum_recompute",
            "no_future_observations",
            "signal_bar_hash",
        },
        "financial_accounting": {
            "cash_unchanged_without_fill",
            "fill_recompute",
            "ledger_recompute",
        },
        "execution_provenance": {
            "information_cutoff",
            "retrieval_cutoff",
            "fill_assumption",
            "not_realtime",
            "missed_not_backfilled",
        },
    }
    scopes = {name: _group_status(checks, names) for name, names in groups.items()}
    required = [
        scopes["evidence_integrity"],
        scopes["signal_recomputation"],
        scopes["financial_accounting"],
        scopes["execution_provenance"],
    ]
    if "FAIL" in required:
        scopes["full_cycle"] = "FAIL"
    elif "INVALID_ARTIFACT" in required:
        scopes["full_cycle"] = "INVALID_ARTIFACT"
    elif "NOT_EVALUABLE" in required:
        scopes["full_cycle"] = "NOT_EVALUABLE"
    elif all(item in {"PASS", "NOT_APPLICABLE"} for item in required):
        scopes["full_cycle"] = "PASS"
    else:
        scopes["full_cycle"] = "NOT_EVALUABLE"
    return scopes


def _group_status(checks: list[Check], names: set[str]) -> str:
    rows = [row for row in checks if row["name"] in names]
    if not rows:
        return "NOT_EVALUABLE"
    statuses = {row["status"] for row in rows}
    if "FAIL" in statuses:
        return "FAIL"
    if "INVALID_ARTIFACT" in statuses:
        return "INVALID_ARTIFACT"
    if "NOT_EVALUABLE" in statuses:
        return "NOT_EVALUABLE"
    if statuses <= {"NOT_APPLICABLE"}:
        return "NOT_APPLICABLE"
    return "PASS"


def _result(
    cycle_id: int,
    status: str,
    checks: list[Check],
    note: str,
    scopes: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "cycle_id": cycle_id,
        "status": status,
        "verified": status == "PASS",
        "scopes": scopes or {},
        "checks": checks,
        "note": note,
    }
