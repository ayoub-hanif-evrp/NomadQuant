"""Risk cash projection must match the shared fill kernel. Numbers are hand-checked."""

from datetime import UTC, datetime
from decimal import Decimal

from nomadquant.finance.accounting import Book, apply_fill
from nomadquant.research.models import CostModel
from nomadquant.risk import InternalLedger, Proposal, RiskEngine, RiskPolicy

WHEN = datetime(2026, 10, 16, 15, 0, tzinfo=UTC)
COSTS = CostModel(
    commission_usd=Decimal("0"),
    spread_bps=Decimal("1"),
    slippage_bps=Decimal("1"),
)


def test_fractional_buy_cash_matches_the_accounting_kernel() -> None:
    quantity = Decimal("0.1")
    mid = Decimal("100")
    book, fill = apply_fill(
        Book(cash=Decimal("100")),
        symbol="SPY",
        side="buy",
        quantity=quantity,
        mid=mid,
        costs=COSTS,
    )
    result = RiskEngine(RiskPolicy()).evaluate(
        Proposal(
            id="parity-1",
            source="test",
            symbol="SPY",
            side="buy",
            quantity=quantity,
            as_of=WHEN,
        ),
        InternalLedger(cash_usd=Decimal("100")),
        {"SPY": {"price": mid, "as_of": WHEN, "feed": "sip"}},
        now=WHEN,
    )
    assert result.verdict == "APPROVE", result.reasons
    assert result.notional_usd == fill.notional == Decimal("10.0015")
    assert result.projected_cash_usd == book.cash == Decimal("89.9985")
    assert result.is_hypothetical is True


def _pair(side: str, qty: str, mid: str, cash: str, policy: RiskPolicy, basis: str | None = None):
    quantity = Decimal(qty)
    price = Decimal(mid)
    book = Book(
        cash=Decimal(cash),
        holdings={} if side == "buy" else {"SPY": quantity if basis else Decimal("1")},
        cost_basis={} if basis is None else {"SPY": Decimal(basis)},
    )
    if side == "sell" and "SPY" not in book.holdings:
        book.holdings["SPY"] = quantity
    updated, fill = apply_fill(
        book, symbol="SPY", side=side, quantity=quantity, mid=price, costs=_costs(policy)
    )
    ledger = InternalLedger(
        cash_usd=Decimal(cash),
        holdings=dict(book.holdings),
    )
    result = RiskEngine(policy).evaluate(
        Proposal(
            id=f"parity-{side}-{qty}",
            source="test",
            symbol="SPY",
            side=side,  # type: ignore[arg-type]
            quantity=quantity,
            as_of=WHEN,
        ),
        ledger,
        {"SPY": {"price": price, "as_of": WHEN, "feed": "sip"}},
        now=WHEN,
        cost_basis=dict(book.cost_basis),
        account=_flat(cash, book.holdings, price),
    )
    return result, updated, fill


def _costs(policy: RiskPolicy) -> CostModel:
    return CostModel(
        commission_usd=policy.commission_usd,
        spread_bps=policy.spread_bps,
        slippage_bps=policy.slippage_bps,
    )


def _flat(cash: str, holdings: dict, price: Decimal):
    from nomadquant.risk import AccountMetrics

    equity = Decimal(cash) + sum(qty * price for qty in holdings.values())
    return AccountMetrics(
        realized_pnl_today_usd=Decimal("0"),
        equity_usd=equity,
        peak_equity_usd=equity,
    )


def test_full_cash_boundary_matches_kernel() -> None:
    mid = Decimal("50") * Decimal(20000) / Decimal(20003)
    result, book, fill = _pair("buy", "1", str(mid), "55", RiskPolicy())
    assert result.verdict == "APPROVE", result.reasons
    assert result.notional_usd == fill.notional == Decimal("50")
    assert result.projected_cash_usd == book.cash == Decimal("5")


def test_buy_with_commission_matches_kernel() -> None:
    policy = RiskPolicy(commission_usd=Decimal("0.50"))
    result, book, fill = _pair("buy", "0.1", "100", "100", policy)
    assert result.verdict == "APPROVE", result.reasons
    assert result.projected_cash_usd == book.cash
    assert fill.commission == Decimal("0.50")
    assert book.cash == Decimal("100") - fill.notional - fill.commission


def test_sell_with_cost_basis_matches_kernel() -> None:
    policy = RiskPolicy()
    price = Decimal("110")
    quantity = Decimal("0.2")
    held = Decimal("0.5")
    basis = Decimal("100")
    cash = Decimal("40")
    book = Book(cash=cash, holdings={"SPY": held}, cost_basis={"SPY": basis})
    updated, fill = apply_fill(
        book, symbol="SPY", side="sell", quantity=quantity, mid=price, costs=_costs(policy)
    )
    result = RiskEngine(policy).evaluate(
        Proposal(
            id="parity-sell",
            source="test",
            symbol="SPY",
            side="sell",
            quantity=quantity,
            as_of=WHEN,
        ),
        InternalLedger(cash_usd=cash, holdings={"SPY": held}),
        {"SPY": {"price": price, "as_of": WHEN, "feed": "sip"}},
        now=WHEN,
        cost_basis={"SPY": basis},
        account=_flat(str(cash), {"SPY": held}, price),
    )
    assert result.verdict == "APPROVE", result.reasons
    assert result.notional_usd == fill.notional
    assert result.projected_cash_usd == updated.cash
    assert updated.realized_pnl > 0


def test_wider_spread_matches_kernel() -> None:
    policy = RiskPolicy(spread_bps=Decimal("10"))
    result, book, fill = _pair("buy", "0.1", "100", "100", policy)
    assert result.verdict == "APPROVE", result.reasons
    assert result.notional_usd == fill.notional
    assert result.projected_cash_usd == book.cash
    assert fill.notional > Decimal("10.0015")


def test_larger_slippage_matches_kernel() -> None:
    policy = RiskPolicy(slippage_bps=Decimal("8"))
    result, book, fill = _pair("buy", "0.1", "100", "100", policy)
    assert result.verdict == "APPROVE", result.reasons
    assert result.notional_usd == fill.notional
    assert result.projected_cash_usd == book.cash


def test_rounded_quantity_matches_kernel() -> None:
    result, book, fill = _pair("buy", "0.123456", "100", "100", RiskPolicy())
    assert result.verdict == "APPROVE", result.reasons
    assert result.notional_usd == fill.notional
    assert result.projected_cash_usd == book.cash


def test_existing_reservation_reduces_available_cash() -> None:
    policy = RiskPolicy()
    ledger = InternalLedger(cash_usd=Decimal("100"), reserved_cash_usd=Decimal("90"))
    result = RiskEngine(policy).evaluate(
        Proposal(
            id="parity-reserved",
            source="test",
            symbol="SPY",
            side="buy",
            quantity=Decimal("0.2"),
            as_of=WHEN,
        ),
        ledger,
        {"SPY": {"price": Decimal("100"), "as_of": WHEN, "feed": "sip"}},
        now=WHEN,
        account=_flat("100", {}, Decimal("100")),
    )
    assert result.verdict == "REJECT"
    assert any(
        row.rule == "available_cash" and row.verdict == "REJECT" for row in result.rule_verdicts
    )


def test_transaction_cap_exact_and_slightly_beyond() -> None:
    exact_mid = Decimal("50") * Decimal(20000) / Decimal(20003)
    exact, _, fill = _pair("buy", "1", str(exact_mid), "100", RiskPolicy())
    assert exact.verdict == "APPROVE", exact.reasons
    assert fill.notional == Decimal("50")
    beyond = RiskEngine(RiskPolicy()).evaluate(
        Proposal(
            id="parity-beyond",
            source="test",
            symbol="SPY",
            side="buy",
            quantity=Decimal("1"),
            as_of=WHEN,
        ),
        InternalLedger(cash_usd=Decimal("100")),
        {"SPY": {"price": Decimal("50"), "as_of": WHEN, "feed": "sip"}},
        now=WHEN,
    )
    assert beyond.verdict == "REJECT"
    assert any(row.rule == "max_single_transaction_usd" for row in beyond.rule_verdicts)


def test_cash_that_covers_mid_but_not_execution_price_is_rejected() -> None:
    result = RiskEngine(RiskPolicy()).evaluate(
        Proposal(
            id="parity-short-cash",
            source="test",
            symbol="SPY",
            side="buy",
            quantity=Decimal("1"),
            as_of=WHEN,
        ),
        InternalLedger(cash_usd=Decimal("10.001")),
        {"SPY": {"price": Decimal("10"), "as_of": WHEN, "feed": "sip"}},
        now=WHEN,
        account=_flat("10.001", {}, Decimal("10")),
    )
    assert result.verdict == "REJECT"
    assert any(row.rule == "available_cash" for row in result.rule_verdicts)


def test_daily_loss_breach_blocks_a_new_buy() -> None:
    from nomadquant.risk import AccountMetrics

    result = RiskEngine(RiskPolicy()).evaluate(
        Proposal(
            id="parity-loss",
            source="test",
            symbol="SPY",
            side="buy",
            quantity=Decimal("0.01"),
            as_of=WHEN,
        ),
        InternalLedger(cash_usd=Decimal("89"), holdings={"SPY": Decimal("0.1")}),
        {"SPY": {"price": Decimal("100"), "as_of": WHEN, "feed": "sip"}},
        now=WHEN,
        account=AccountMetrics(
            realized_pnl_today_usd=Decimal("-10.01"),
            equity_usd=Decimal("99"),
            peak_equity_usd=Decimal("100"),
        ),
    )
    assert result.verdict == "REJECT"
    assert any(row.rule == "realized_daily_loss" for row in result.rule_verdicts)


def test_drawdown_breach_blocks_a_new_buy() -> None:
    from nomadquant.risk import AccountMetrics

    result = RiskEngine(RiskPolicy()).evaluate(
        Proposal(
            id="parity-dd",
            source="test",
            symbol="SPY",
            side="buy",
            quantity=Decimal("0.01"),
            as_of=WHEN,
        ),
        InternalLedger(cash_usd=Decimal("40"), holdings={"SPY": Decimal("0.3")}),
        {"SPY": {"price": Decimal("100"), "as_of": WHEN, "feed": "sip"}},
        now=WHEN,
        account=AccountMetrics(
            realized_pnl_today_usd=Decimal("0"),
            equity_usd=Decimal("70"),
            peak_equity_usd=Decimal("100"),
        ),
    )
    assert result.verdict == "REJECT"
    assert any(row.rule == "unrealized_drawdown" for row in result.rule_verdicts)


def test_missing_day_pnl_with_holdings_is_insufficient_data() -> None:
    result = RiskEngine(RiskPolicy()).evaluate(
        Proposal(
            id="parity-missing",
            source="test",
            symbol="SPY",
            side="buy",
            quantity=Decimal("0.01"),
            as_of=WHEN,
        ),
        InternalLedger(cash_usd=Decimal("50"), holdings={"SPY": Decimal("0.1")}),
        {"SPY": {"price": Decimal("100"), "as_of": WHEN, "feed": "sip"}},
        now=WHEN,
    )
    assert result.verdict == "INSUFFICIENT_DATA"
    assert any(row.rule == "realized_daily_loss" for row in result.rule_verdicts)


def test_untouched_cash_book_uses_documented_zero_day_loss() -> None:
    result = RiskEngine(RiskPolicy()).evaluate(
        Proposal(
            id="parity-init",
            source="test",
            symbol="SPY",
            side="buy",
            quantity=Decimal("0.01"),
            as_of=WHEN,
        ),
        InternalLedger(cash_usd=Decimal("100")),
        {"SPY": {"price": Decimal("100"), "as_of": WHEN, "feed": "sip"}},
        now=WHEN,
    )
    assert result.verdict == "APPROVE", result.reasons
    assert any(
        row.rule == "realized_daily_loss" and row.verdict == "PASS" for row in result.rule_verdicts
    )
