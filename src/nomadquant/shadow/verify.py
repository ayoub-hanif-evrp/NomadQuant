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

VERIFY_EXIT_CODES = {
    "PASS": 0,
    "FAIL": 1,
    "NOT_EVALUABLE": 2,
    "INVALID_ARTIFACT": 3,
}


def verification_exit_code(status: str) -> int:
    """Shell contract for every verifier status. Unknown statuses are failures."""
    return VERIFY_EXIT_CODES.get(status, 1)


def verify_cycle(settings: Settings, cycle_id: int) -> dict[str, Any]:
    """Recompute what the cycle should show. Do not trust its stored totals alone."""
    path = Path(settings.shadow_path)
    if not path.exists():
        return _result(cycle_id, "INVALID_ARTIFACT", [], "shadow ledger is missing")
    shadow = ShadowStore.open_readonly(path)
    if shadow is None:
        return _result(cycle_id, "INVALID_ARTIFACT", [], "shadow ledger is missing")
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
        checks.extend(_recompute_fill(cycle, evidence, market, shadow))
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


def _recorded_costs(evidence: dict[str, Any]) -> CostModel | None:
    raw = evidence.get("cost_model")
    if not isinstance(raw, dict):
        return None
    try:
        return CostModel(
            commission_usd=Decimal(str(raw["commission_usd"])),
            spread_bps=Decimal(str(raw["spread_bps"])),
            slippage_bps=Decimal(str(raw["slippage_bps"])),
        )
    except (KeyError, ValueError, ArithmeticError):
        return None


def _money_match(actual: Decimal, stored: object) -> bool:
    try:
        return actual == Decimal(str(stored))
    except (ArithmeticError, ValueError):
        return False


def _map_match(actual: dict[str, Decimal], stored: object) -> bool:
    if not isinstance(stored, dict):
        return False
    left = {str(k): str(v) for k, v in actual.items()}
    right = {str(k): str(v) for k, v in stored.items()}
    return left == right


def _recompute_fill(
    cycle: dict[str, Any],
    evidence: dict[str, Any],
    market: MarketStore,
    shadow: ShadowStore,
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
    if convention == LEGACY_SHADOW_CONVENTION_ID:
        return [
            _check(
                "fill_recompute",
                "NOT_EVALUABLE",
                "legacy convention is recognized and is not replayed with guessed costs",
            )
        ]
    if convention != CONVENTION_ID:
        return [
            _check(
                "fill_recompute",
                "NOT_EVALUABLE",
                "execution convention was not recorded on this cycle",
            )
        ]
    costs = _recorded_costs(evidence)
    if costs is None:
        return [
            _check(
                "fill_recompute",
                "NOT_EVALUABLE",
                "the cost model used for this fill was not recorded",
            )
        ]
    expected = execution_price(bar.open, costs, side=side)
    raw_fill = evidence.get("fill")
    meta: dict[str, Any] = raw_fill if isinstance(raw_fill, dict) else {}
    meta_qty = meta.get("quantity")
    if meta_qty is None:
        quantity_status = "NOT_EVALUABLE"
    else:
        try:
            quantity_ok = Decimal(str(qty_raw)) == Decimal(str(meta_qty))
            quantity_status = "PASS" if quantity_ok else "FAIL"
        except (ArithmeticError, ValueError):
            quantity_status = "FAIL"
    checks = [
        _check(
            "fill_recompute",
            "PASS" if Decimal(str(stored_price)) == expected else "FAIL",
            f"recomputed {expected} from the stored open using {convention}",
        ),
        _check("fill_quantity", quantity_status, str(qty_raw)),
    ]
    checks.extend(_signal_timestamps(evidence))
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
        updated, fill = apply_fill(
            book,
            symbol=SYMBOL,
            side=side,
            quantity=Decimal(str(qty_raw)),
            mid=bar.open,
            costs=costs,
        )
    except (ValueError, KeyError, ArithmeticError) as exc:
        checks.append(_check("ledger_recompute", "FAIL", type(exc).__name__))
        return checks
    reserved_after = Decimal("0")
    equity = updated.cash + updated.holdings.get(SYMBOL, Decimal("0")) * bar.open
    checks.extend(
        [
            _check(
                "cash_after",
                "PASS" if _money_match(updated.cash, after.get("cash_usd")) else "FAIL",
                str(updated.cash),
            ),
            _check(
                "reserved_cash",
                "PASS" if _money_match(reserved_after, after.get("reserved_cash_usd")) else "FAIL",
                "reservation is released on the fill",
            ),
            _check(
                "holdings_after",
                "PASS" if _map_match(updated.holdings, after.get("holdings")) else "FAIL",
                "holdings recomputed from the pre-fill book",
            ),
            _check(
                "cost_basis",
                "PASS" if _map_match(updated.cost_basis, after.get("cost_basis")) else "FAIL",
                "average cost recomputed from the fill",
            ),
            _check(
                "realized_pnl",
                "PASS"
                if _money_match(updated.realized_pnl, after.get("realized_pnl_usd"))
                else "FAIL",
                str(updated.realized_pnl),
            ),
            _check(
                "total_costs",
                "PASS"
                if _money_match(updated.attributed_costs, after.get("total_costs_usd"))
                else "FAIL",
                str(updated.attributed_costs),
            ),
            _check(
                "commission_spread_slippage",
                "PASS"
                if _money_match(
                    fill.spread_cost + fill.slippage_cost + fill.commission,
                    Decimal(str(cycle.get("costs_usd") or "nan")),
                )
                else "FAIL",
                "attributed spread, slippage, and commission",
            ),
            _check(
                "ledger_version",
                "PASS"
                if after.get("version") is not None
                and int(after["version"]) == int(before.get("version") or 0) + 1
                else "NOT_EVALUABLE"
                if after.get("version") is None
                else "FAIL",
                "fill snapshot version is the pre-fill version plus one",
            ),
        ]
    )
    history = shadow.equity_history(limit=5000)
    point = next((row for row in history if row["cycle_id"] == cycle.get("id")), None)
    if point is None:
        checks.append(
            _check("equity_journal", "NOT_EVALUABLE", "no equity journal row for this fill")
        )
    else:
        checks.append(
            _check(
                "equity_journal",
                "PASS" if _money_match(equity, point.get("equity_usd")) else "FAIL",
                str(equity),
            )
        )
    proposal_id = str(cycle.get("proposal_id") or "")
    siblings = [
        row
        for row in shadow.list_cycles(limit=5000)
        if row.get("status") == "filled" and str(row.get("proposal_id") or "") == proposal_id
    ]
    checks.append(
        _check(
            "duplicate_fill",
            "FAIL"
            if proposal_id and len(siblings) > 1
            else "PASS"
            if proposal_id
            else "NOT_EVALUABLE",
            f"{len(siblings)} filled cycle(s) share this proposal",
        )
    )
    stored_hash = str(evidence.get("policy_hash") or "")
    outbox_rows = shadow.list_outbox(limit=5000)
    matched = [
        row
        for row in outbox_rows
        if str((row.get("payload") or {}).get("proposal_id") or "") == proposal_id
    ]
    if not stored_hash:
        checks.append(_check("policy_hash", "NOT_EVALUABLE", "policy hash was not stored"))
    elif matched and str(matched[0]["payload"].get("policy_hash") or "") != stored_hash:
        checks.append(
            _check("policy_hash", "FAIL", "evidence policy hash disagrees with the outbox")
        )
    else:
        checks.append(_check("policy_hash", "PASS", stored_hash))
    checks.append(
        _check(
            "outbox_reference",
            "PASS" if matched else "FAIL",
            "a risk outbox row references this proposal",
        )
    )
    checks.append(
        _check(
            "ledger_recompute",
            "PASS",
            "field checks above are the financial recompute",
        )
    )
    return checks


def _signal_timestamps(evidence: dict[str, Any]) -> list[Check]:
    names = (
        "signal_created_at",
        "signal_information_cutoff",
        "observation_market_timestamp",
        "observation_first_retrieved_at",
        "risk_evaluated_at",
        "simulation_processed_at",
    )
    missing = [name for name in names if not evidence.get(name)]
    if missing:
        return [
            _check(
                "signal_timing",
                "NOT_EVALUABLE",
                "missing " + ", ".join(missing),
            )
        ]
    parsed = [_parse(str(evidence[name])) for name in names]
    if any(item is None for item in parsed):
        return [_check("signal_timing", "INVALID_ARTIFACT", "a timestamp did not parse")]
    retrieved = parsed[3]
    evaluated = parsed[4]
    assert retrieved is not None and evaluated is not None
    if retrieved > evaluated:
        return [
            _check(
                "signal_timing",
                "FAIL",
                "observation was retrieved after the risk evaluation",
            )
        ]
    return [_check("signal_timing", "PASS", "recorded clocks are ordered")]


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
            "fill_quantity",
            "ledger_recompute",
            "cash_after",
            "reserved_cash",
            "holdings_after",
            "cost_basis",
            "realized_pnl",
            "total_costs",
            "commission_spread_slippage",
            "equity_journal",
            "ledger_version",
            "duplicate_fill",
        },
        "execution_provenance": {
            "information_cutoff",
            "retrieval_cutoff",
            "fill_assumption",
            "not_realtime",
            "missed_not_backfilled",
            "signal_timing",
            "policy_hash",
            "outbox_reference",
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
