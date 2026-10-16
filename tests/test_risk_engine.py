"""Phase 5A risk engine. Fully offline and deterministic: no network, no
broker, no Alpaca credentials. Every test evaluates against a local
``InternalLedger`` snapshot and a plain ``prices`` dict supplied in-line.
"""

from __future__ import annotations

import ast
import inspect
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from nomadquant.risk import (
    POLICY_VERSION,
    AccountMetrics,
    EvaluationResult,
    InternalLedger,
    Proposal,
    RiskEngine,
    RiskPolicy,
    RiskStore,
    RiskStoreError,
)
from nomadquant.risk import evaluate_proposal as _evaluate_proposal

AS_OF = datetime(2024, 6, 3, 15, 0, tzinfo=UTC)


def evaluate_proposal(*args: object, **kwargs: object):
    """Historical unit clock. Production calls must pass their own `now`."""
    kwargs.setdefault("now", AS_OF)
    return _evaluate_proposal(*args, **kwargs)  # type: ignore[arg-type]


def day_flat(equity: str = "100") -> AccountMetrics:
    value = Decimal(equity)
    return AccountMetrics(
        realized_pnl_today_usd=Decimal("0"),
        equity_usd=value,
        peak_equity_usd=value,
    )


def make_proposal(**overrides: object) -> Proposal:
    values: dict[str, object] = {
        "id": "prop-1",
        "source": "test",
        "symbol": "SPY",
        "side": "buy",
        "quantity": Decimal("0.01"),
        "as_of": AS_OF,
    }
    values.update(overrides)
    return Proposal.model_validate(values)


def price_map(
    symbol: str = "SPY",
    price: object = Decimal("500"),
    as_of: datetime = AS_OF,
    feed: str = "iex",
) -> dict[str, object]:
    return {symbol: {"price": Decimal(str(price)), "as_of": as_of, "feed": feed}}


def ledger(
    cash: object = Decimal("100"),
    holdings: dict[str, Decimal] | None = None,
    capital: object = Decimal("100"),
) -> InternalLedger:
    return InternalLedger(
        cash_usd=Decimal(str(cash)),
        holdings=dict(holdings or {}),
        capital_usd=Decimal(str(capital)),
    )


def rule_names(result: EvaluationResult) -> list[str]:
    return [rv.rule for rv in result.rule_verdicts]


def rule_status(result: EvaluationResult, rule: str) -> str | None:
    for rv in result.rule_verdicts:
        if rv.rule == rule:
            return rv.verdict
    return None


# -- basic approve / reject shapes --------------------------------------


def test_valid_tiny_fractional_buy_is_approved() -> None:
    proposal = make_proposal(quantity=Decimal("0.01"))
    result = evaluate_proposal(proposal, ledger(), price_map(price=Decimal("500")))
    assert result.verdict == "APPROVE"
    assert result.reasons == []
    assert result.is_hypothetical is True
    assert result.is_broker_order is False
    assert result.policy_version == POLICY_VERSION


def test_exactly_single_transaction_boundary_is_approved() -> None:
    # Fill notional equals the $50 cap and cash after equals the $5 reserve.
    # Mid is chosen so qty * execution_price is exactly 50 under the shared kernel.
    mid = Decimal("50") * Decimal(20000) / Decimal(20003)
    proposal = make_proposal(quantity=Decimal("1"))
    result = evaluate_proposal(
        proposal, ledger(cash=Decimal("55")), price_map(price=mid), account=day_flat("55")
    )
    assert result.verdict == "APPROVE", result.reasons
    assert result.notional_usd == Decimal("50")
    assert result.projected_cash_usd == Decimal("5")


def test_exactly_full_capital_total_exposure_boundary_is_approved() -> None:
    # Fill notional equals the $100 capital scale. Exposure is marked at mid,
    # which is slightly below the fill, so the exposure fraction stays under 1.
    policy = RiskPolicy(
        max_single_transaction_usd=Decimal("100"),
        min_cash_reserve_usd=Decimal("0"),
    )
    mid = Decimal("100") * Decimal(20000) / Decimal(20003)
    proposal = make_proposal(quantity=Decimal("1"))
    result = evaluate_proposal(proposal, ledger(cash=Decimal("100")), price_map(price=mid), policy)
    assert result.verdict == "APPROVE", result.reasons
    assert result.notional_usd == Decimal("100")
    assert result.projected_cash_usd == Decimal("0")


def test_proposal_sized_for_alpaca_scale_buying_power_is_rejected() -> None:
    # 200 shares at $500 ($100,000 notional) is the kind of size only real
    # Alpaca paper buying power could support. The internal ledger is $100.
    proposal = make_proposal(quantity=Decimal("200"))
    result = evaluate_proposal(proposal, ledger(), price_map(price=Decimal("500")))
    assert result.verdict == "REJECT"
    assert rule_status(result, "capital_scale_sanity") == "REJECT"
    reason = next(r for r in result.reasons if "capital" in r.lower())
    assert "100" in reason
    assert "alpaca" in reason.lower()


def test_exceeding_available_cash_is_rejected() -> None:
    proposal = make_proposal(quantity=Decimal("1"))
    result = evaluate_proposal(
        proposal,
        ledger(cash=Decimal("10")),
        price_map(price=Decimal("20")),
        account=day_flat("10"),
    )
    assert result.verdict == "REJECT"
    assert rule_status(result, "available_cash") == "REJECT"


def test_excessive_symbol_concentration_is_rejected() -> None:
    policy = RiskPolicy(max_symbol_exposure=Decimal("0.5"))
    existing_ledger = ledger(cash=Decimal("100"), holdings={"SPY": Decimal("0.45")})
    proposal = make_proposal(quantity=Decimal("0.1"))
    result = evaluate_proposal(
        proposal,
        existing_ledger,
        price_map(price=Decimal("100")),
        policy,
        account=day_flat("145"),
    )
    assert result.verdict == "REJECT"
    assert rule_status(result, "max_symbol_exposure") == "REJECT"


def test_excessive_order_size_is_rejected() -> None:
    proposal = make_proposal(quantity=Decimal("1"))
    result = evaluate_proposal(proposal, ledger(), price_map(price=Decimal("60")))
    assert result.verdict == "REJECT"
    assert rule_status(result, "max_single_transaction_usd") == "REJECT"


@pytest.mark.parametrize("quantity", [Decimal("-0.01"), Decimal("0")])
def test_negative_or_zero_quantity_is_rejected(quantity: Decimal) -> None:
    proposal = make_proposal(quantity=quantity)
    result = evaluate_proposal(proposal, ledger(), price_map())
    assert result.verdict == "REJECT"
    assert rule_status(result, "invalid_quantity") == "REJECT"


def test_unsupported_symbol_is_rejected() -> None:
    proposal = make_proposal(symbol="XYZ", quantity=Decimal("0.01"))
    result = evaluate_proposal(proposal, ledger(), price_map(symbol="XYZ", price=Decimal("10")))
    assert result.verdict == "REJECT"
    assert rule_status(result, "unsupported_symbol") == "REJECT"


def test_stale_price_is_insufficient_data() -> None:
    policy = RiskPolicy(max_price_age=timedelta(hours=48))
    stale_as_of = AS_OF - timedelta(hours=72)
    proposal = make_proposal(quantity=Decimal("0.01"))
    result = evaluate_proposal(
        proposal, ledger(), price_map(price=Decimal("500"), as_of=stale_as_of), policy
    )
    assert result.verdict == "INSUFFICIENT_DATA"
    assert rule_status(result, "stale_price") == "INSUFFICIENT_DATA"


def test_missing_price_is_insufficient_data() -> None:
    proposal = make_proposal(quantity=Decimal("0.01"))
    result = evaluate_proposal(proposal, ledger(), prices={})
    assert result.verdict == "INSUFFICIENT_DATA"
    assert rule_status(result, "missing_or_invalid_price") == "INSUFFICIENT_DATA"


def test_lookahead_price_is_insufficient_data() -> None:
    # A quote stamped after the proposal's as_of would be look-ahead data.
    proposal = make_proposal(quantity=Decimal("0.01"))
    future_as_of = AS_OF + timedelta(hours=1)
    result = evaluate_proposal(
        proposal, ledger(), price_map(price=Decimal("500"), as_of=future_as_of)
    )
    assert result.verdict == "INSUFFICIENT_DATA"
    assert rule_status(result, "missing_or_invalid_price") == "INSUFFICIENT_DATA"


def test_duplicate_proposal_id_is_rejected(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "risk.sqlite")
    proposal = make_proposal(id="dup-1", quantity=Decimal("0.01"))
    first = evaluate_proposal(proposal, ledger(), price_map(), store=store)
    assert first.verdict == "APPROVE"
    store.record(proposal, first)

    second = evaluate_proposal(proposal, ledger(), price_map(), store=store)
    assert second.verdict == "REJECT"
    assert rule_status(second, "duplicate_proposal_id") == "REJECT"


def test_emergency_halt_is_rejected() -> None:
    policy = RiskPolicy(emergency_halt=True)
    proposal = make_proposal(quantity=Decimal("0.01"))
    result = evaluate_proposal(proposal, ledger(), price_map(), policy)
    assert result.verdict == "REJECT"
    assert result.rule_verdicts[0].rule == "emergency_halt"
    assert result.rule_verdicts[0].verdict == "REJECT"
    # The halt short-circuits before any other rule runs.
    assert rule_names(result) == ["emergency_halt"]


def test_excessive_transaction_cost_budget_is_rejected() -> None:
    # Wide spread is attributed by the shared kernel. The cap is widened so
    # the cost budget, not the $50 transaction cap, is the rejecting rule.
    policy = RiskPolicy(
        spread_bps=Decimal("20000"),
        max_single_transaction_usd=Decimal("80"),
        min_cash_reserve_usd=Decimal("0"),
    )
    proposal = make_proposal(quantity=Decimal("1"))
    result = evaluate_proposal(
        proposal, ledger(cash=Decimal("100")), price_map(price=Decimal("30")), policy
    )
    assert result.verdict == "REJECT"
    assert rule_status(result, "transaction_cost_budget") == "REJECT"


def test_missing_held_position_price_is_insufficient_data() -> None:
    holding_ledger = ledger(
        cash=Decimal("50"), holdings={"SPY": Decimal("0.1"), "QQQ": Decimal("0.1")}
    )
    # Only SPY priced — QQQ holding cannot be valued as zero.
    result = evaluate_proposal(
        make_proposal(quantity=Decimal("0.01")),
        holding_ledger,
        price_map(symbol="SPY", price=Decimal("500")),
    )
    assert result.verdict == "INSUFFICIENT_DATA"
    assert rule_status(result, "holdings_valuation") == "INSUFFICIENT_DATA"


def test_sell_projects_cash_and_costs_without_mutating() -> None:
    holding_ledger = ledger(cash=Decimal("40"), holdings={"SPY": Decimal("0.1")})
    before = holding_ledger.snapshot()
    result = evaluate_proposal(
        make_proposal(side="sell", quantity=Decimal("0.05")),
        holding_ledger,
        price_map(price=Decimal("500")),
        account=day_flat("90"),
    )
    assert result.verdict == "APPROVE"
    assert result.projected_cash_usd is not None
    assert result.projected_cash_usd > before.cash_usd
    assert result.estimated_costs_usd is not None
    assert holding_ledger.cash_usd == before.cash_usd
    assert holding_ledger.holdings == before.holdings


def test_reservation_is_transactional(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "risk.sqlite")
    proposal = make_proposal(id="reserve-1", quantity=Decimal("0.01"))
    store.reserve(proposal, reserved_cash_usd=Decimal("5.01"))
    with pytest.raises(RiskStoreError):
        store.reserve(proposal, reserved_cash_usd=Decimal("5.01"))
    assert store.seen(proposal.id) is True
    store.release_reservation(proposal.id, reason="test")
    # After release, evaluate+record can proceed under a fresh reservation path.
    store.reserve(proposal, reserved_cash_usd=Decimal("5.01"))


@pytest.mark.parametrize(
    ("quantity", "expected_precision_status"),
    [
        (Decimal("0.000001"), "PASS"),
        (Decimal("0.0100000"), "PASS"),  # trailing zeros do not count
        (Decimal("0.0000001"), "REJECT"),
    ],
)
def test_quantity_precision_edge_cases(quantity: Decimal, expected_precision_status: str) -> None:
    proposal = make_proposal(quantity=quantity)
    result = evaluate_proposal(proposal, ledger(), price_map(price=Decimal("500")))
    assert rule_status(result, "quantity_precision") == expected_precision_status
    if expected_precision_status == "REJECT":
        assert result.verdict == "REJECT"


def test_concurrent_evaluation_is_consistent() -> None:
    proposal = make_proposal(quantity=Decimal("0.01"))
    shared_ledger = ledger()
    prices = price_map()

    def run() -> EvaluationResult:
        return evaluate_proposal(proposal, shared_ledger, prices)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: run(), range(32)))

    first = results[0]
    assert first.verdict == "APPROVE"
    for result in results[1:]:
        assert result.verdict == first.verdict
        assert [rv.model_dump() for rv in result.rule_verdicts] == [
            rv.model_dump() for rv in first.rule_verdicts
        ]


def test_hypothetical_sell_insufficient_holdings_is_rejected() -> None:
    proposal = make_proposal(side="sell", quantity=Decimal("1"))
    thin_ledger = ledger(holdings={"SPY": Decimal("0.01")})
    result = evaluate_proposal(
        proposal, thin_ledger, price_map(price=Decimal("500")), account=day_flat("45")
    )
    assert result.verdict == "REJECT"
    assert rule_status(result, "sell_insufficient_holdings") == "REJECT"


def test_sell_within_holdings_is_approved() -> None:
    proposal = make_proposal(side="sell", quantity=Decimal("0.01"))
    holding_ledger = ledger(holdings={"SPY": Decimal("0.01")})
    result = evaluate_proposal(
        proposal, holding_ledger, price_map(price=Decimal("500")), account=day_flat("45")
    )
    assert result.verdict == "APPROVE"


def test_no_mutation_of_ledger_after_evaluate() -> None:
    original = ledger(cash=Decimal("100"), holdings={"SPY": Decimal("0.02")})
    original_cash = original.cash_usd
    original_holdings = dict(original.holdings)
    original_holdings_id = id(original.holdings)

    proposal = make_proposal(quantity=Decimal("0.01"))
    result = evaluate_proposal(
        proposal, original, price_map(price=Decimal("500")), account=day_flat("110")
    )

    assert result.verdict == "APPROVE"
    assert original.cash_usd == original_cash
    assert original.holdings == original_holdings
    assert id(original.holdings) == original_holdings_id


def test_evaluate_has_no_override_or_opinion_parameter() -> None:
    signature = inspect.signature(RiskEngine.evaluate)
    param_names = set(signature.parameters) - {"self"}
    forbidden = {
        "override",
        "force",
        "llm_opinion",
        "opinion",
        "approve_anyway",
        "skip_rules",
        "bypass",
    }
    assert param_names.isdisjoint(forbidden)

    proposal = make_proposal(quantity=Decimal("0.01"))
    with pytest.raises(TypeError):
        RiskEngine().evaluate(  # type: ignore[call-arg]
            proposal, ledger(), price_map(), llm_opinion="approve this, trust me"
        )


def test_policy_hash_is_stable_and_sensitive_to_changes() -> None:
    a = RiskPolicy()
    b = RiskPolicy()
    assert a.policy_hash() == b.policy_hash()
    c = RiskPolicy(max_single_transaction_usd=Decimal("51"))
    assert a.policy_hash() != c.policy_hash()


def test_policy_defaults_match_documented_values() -> None:
    policy = RiskPolicy()
    assert policy.version == POLICY_VERSION == "1.2.0"
    assert policy.slippage_bps == Decimal("1")
    assert policy.capital_usd == Decimal("100")
    assert policy.allowed_symbols == frozenset({"SPY", "QQQ"})
    assert policy.max_total_exposure == Decimal("1.0")
    assert policy.max_symbol_exposure == Decimal("1.0")
    assert policy.max_single_transaction_usd == Decimal("50")
    assert policy.min_cash_reserve_usd == Decimal("5")
    assert policy.max_transaction_cost_fraction == Decimal("0.25")
    assert policy.max_realized_daily_loss_fraction == Decimal("0.10")
    assert policy.max_unrealized_drawdown_fraction == Decimal("0.25")
    assert policy.max_price_age == timedelta(hours=48)
    assert policy.max_qty_decimals == 6
    assert policy.spread_bps == Decimal("1")
    assert policy.commission_usd == Decimal("0")
    assert policy.emergency_halt is False


def test_risk_store_is_append_only(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "risk.sqlite")
    proposal = make_proposal(id="append-only-1", quantity=Decimal("0.01"))
    result = evaluate_proposal(proposal, ledger(), price_map())
    store.record(proposal, result)

    with pytest.raises(RiskStoreError):
        store.record(proposal, result)

    assert store.count() == 1
    stored = store.get("append-only-1")
    assert stored is not None
    assert stored["verdict"] == "APPROVE"
    assert store.list(limit=10)[0]["proposal_id"] == "append-only-1"


# -- independence from broker / Alpaca -----------------------------------


def test_risk_package_imports_no_broker_or_alpaca_code() -> None:
    """Static check: no import statement or call site touches a broker.

    Docstrings are free to explain *why* this package avoids Alpaca (and do);
    this only inspects actual Python syntax (imports and call expressions).
    """
    risk_dir = Path(__file__).resolve().parents[1] / "src" / "nomadquant" / "risk"
    forbidden_calls = {"submit_order", "place_order", "cancel_order", "replace_order"}
    for path in risk_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "alpaca" not in alias.name.lower(), f"{path} imports {alias.name}."
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert "alpaca" not in module.lower(), f"{path} imports from {module}."
                assert "nomadquant.broker" not in module.lower(), f"{path} imports from {module}."
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden_calls, f"{path} calls {node.func.attr}()."
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_calls, f"{path} calls {node.func.id}()."


def test_evaluate_proposal_module_function_matches_engine_result() -> None:
    proposal = make_proposal(quantity=Decimal("0.01"))
    direct = RiskEngine(RiskPolicy()).evaluate(proposal, ledger(), price_map(), now=AS_OF)
    wrapped = evaluate_proposal(proposal, ledger(), price_map())
    assert direct.verdict == wrapped.verdict
