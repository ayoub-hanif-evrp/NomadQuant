"""Forward performance reads the isolated ledger instead of placeholder zeros."""

from decimal import Decimal

from nomadquant.finance.accounting import Book, apply_fill, economic_identity
from nomadquant.research.models import CostModel
from nomadquant.shadow.performance import performance_from_store
from nomadquant.shadow.store import ShadowStore

_FREE = CostModel(
    commission_usd=Decimal("0"),
    spread_bps=Decimal("0"),
    slippage_bps=Decimal("0"),
    min_notional_usd=Decimal("1"),
    quantity_precision=6,
)


def test_buy_then_sell_populates_every_forward_metric(tmp_path) -> None:
    store = ShadowStore(tmp_path / "shadow.sqlite", namespace="forward")
    bought = apply_fill(
        Book(cash=Decimal("100")),
        symbol="SPY",
        side="buy",
        quantity=Decimal("1"),
        mid=Decimal("40"),
        costs=_FREE,
    )[0]
    _record(store, "buy", bought, equity=Decimal("110"), mark=Decimal("50"), version=1)
    sold = apply_fill(
        bought, symbol="SPY", side="sell", quantity=Decimal("1"), mid=Decimal("50"), costs=_FREE
    )[0]
    _record(store, "sell", sold, equity=Decimal("110"), mark=Decimal("50"), version=2)
    report = performance_from_store(store)
    assert report["cash_usd"] == "110"
    assert report["holdings"] == {}
    assert report["equity_usd"] == "110"
    assert report["realized_pnl_usd"] == "10"
    assert report["unrealized_pnl_usd"] == "0"
    assert report["prospective_fills"] == 2
    assert [item["side"] for item in report["trade_history"]] == ["sell", "buy"]
    assert report["sample_note"].startswith("The forward ledger has 2")
    identity = economic_identity(
        Book(cash=sold.cash, realized_pnl=sold.realized_pnl),
        {},
        starting=Decimal("100"),
    )
    assert identity["status"] == "PASS"


def test_empty_forward_book_stays_an_empty_state(tmp_path) -> None:
    store = ShadowStore(tmp_path / "shadow.sqlite", namespace="forward")
    report = performance_from_store(store)
    assert report["cash_usd"] == "100"
    assert report["prospective_fills"] == 0
    assert report["trade_history"] == []
    assert "no completed simulated fill" in report["sample_note"]


def test_positive_signal_buy_is_capped_by_the_operational_policy() -> None:
    from nomadquant.risk.policy import RiskPolicy
    from nomadquant.shadow.sizing import size_policy_aware

    sized = size_policy_aware(
        cash=Decimal("100"),
        reserved=Decimal("0"),
        qty=Decimal("0"),
        target_weight=Decimal("1"),
        price=Decimal("100"),
        costs=_FREE,
        policy=RiskPolicy(),
    )
    assert sized.side == "buy"
    assert sized.is_partial is True
    assert sized.quantity * sized.limit_price <= Decimal("50")
    assert Decimal("100") - sized.quantity * sized.limit_price >= Decimal("5")


def _record(
    store: ShadowStore, side: str, book: Book, *, equity: Decimal, mark: Decimal, version: int
) -> None:
    before = store.snapshot()
    after = {
        "cash_usd": book.cash,
        "reserved_cash_usd": Decimal("0"),
        "holdings": dict(book.holdings),
        "cost_basis": dict(book.cost_basis),
        "realized_pnl_usd": book.realized_pnl,
        "total_costs_usd": book.attributed_costs,
        "peak_equity_usd": max(before["peak_equity_usd"], equity),
    }
    store.apply_cycle(
        cycle_key=f"fixture:{side}",
        payload={
            "created_at": "2024-01-03T21:00:00+00:00",
            "mode": "apply",
            "label": "forward_shadow",
            "signal_session": "2024-01-02",
            "fill_session": "2024-01-03",
            "feed": "sip",
            "symbol": "SPY",
            "status": "filled",
            "intent": side,
            "target_weight": "1",
            "momentum": "0.1",
            "proposal_id": f"fixture-{side}",
            "risk_verdict": "APPROVE",
            "risk_reasons": [],
            "fill_price": str(mark if side == "sell" else Decimal("40")),
            "fill_qty": "1",
            "fill_side": side,
            "costs_usd": "0",
            "evidence": {},
            "evidence_hash": side,
            "warnings": [],
            "error_safe": "",
            "duration_ms": 0,
            "ledger_before": before,
            "ledger_after": after,
        },
        ledger_after=after,
        equity_point={
            "recorded_at": "2024-01-03T21:00:00+00:00",
            "session": "2024-01-03",
            "equity_usd": equity,
            "cash_usd": book.cash,
            "exposure_usd": equity - book.cash,
            "realized_pnl_usd": book.realized_pnl,
            "unrealized_pnl_usd": equity - book.cash - sum(book.cost_basis.values(), Decimal("0")),
        },
        expected_version=version,
    )
