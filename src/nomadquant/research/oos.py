"""Out-of-sample path for the locked daily rules.

A signal at the close is filled at the next session's close. Parameters are
not changed here.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_DOWN, Decimal

from nomadquant.daily.engine import primary_candidate
from nomadquant.daily.indicators import trailing_return
from nomadquant.daily.registry import TREND
from nomadquant.research.models import EquityPoint, SimulatedTrade

CAPITAL = Decimal("100")
RESERVE = Decimal("5")
STEP = Decimal("0.000001")
WARMUP = 200


class OosPath:
    def __init__(
        self,
        equity: list[EquityPoint],
        trades: list[SimulatedTrade],
        fold_returns: list[Decimal],
        regimes: dict[str, Decimal],
        matched_return: Decimal | None,
        full_return: Decimal | None,
        status: str,
    ) -> None:
        self.equity = equity
        self.trades = trades
        self.fold_returns = fold_returns
        self.regimes = regimes
        self.matched_return = matched_return
        self.full_return = full_return
        self.status = status

    @property
    def opening(self) -> Decimal:
        return CAPITAL if len(self.equity) <= WARMUP else self.equity[WARMUP - 1].equity

    @property
    def out_of_sample(self) -> list[EquityPoint]:
        return self.equity[WARMUP:]


def simulate(
    prices: dict[str, dict[date, Decimal]],
    sessions: list[date],
    *,
    spread_bps: Decimal,
    slippage_bps: Decimal,
    folds: int = 3,
) -> OosPath:
    usable = [
        day
        for day in sorted(set(sessions))
        if day in (prices.get("SPY") or {}) and day in (prices.get("QQQ") or {})
    ]
    if len(usable) < WARMUP + folds:
        return OosPath([], [], [], {}, None, None, "insufficient_history")
    cash = CAPITAL
    qty = {"SPY": Decimal("0"), "QQQ": Decimal("0")}
    pending: dict[str, str] | None = None
    equity: list[EquityPoint] = []
    trades: list[SimulatedTrade] = []
    for index, day in enumerate(usable):
        if pending is not None:
            cash = _execute(
                pending,
                day,
                prices,
                qty,
                trades,
                cash,
                spread_bps=spread_bps,
                slippage_bps=slippage_bps,
            )
            pending = None
        marked = _equity(cash, qty, prices, day)
        exposure = Decimal("0") if marked <= 0 else (marked - cash) / marked
        equity.append(
            EquityPoint(
                session_date=day,
                equity=marked,
                cash=cash,
                exposure=exposure,
                drawdown=Decimal("0"),
                window="warmup" if index < WARMUP else "out_of_sample",
            )
        )
        if index + 1 < len(usable):
            pending = primary_candidate(prices, day, qty)
    opening = equity[WARMUP - 1].equity
    fold_returns = _folds(equity, opening, folds)
    return OosPath(
        equity,
        trades,
        fold_returns,
        _regimes(prices, usable, equity),
        _hold(prices, usable, TREND.notional_cap, spread_bps, slippage_bps),
        _hold(prices, usable, CAPITAL - RESERVE, spread_bps, slippage_bps),
        "completed",
    )


def _execute(
    choice: dict[str, str],
    day: date,
    prices: dict[str, dict[date, Decimal]],
    qty: dict[str, Decimal],
    trades: list[SimulatedTrade],
    cash: Decimal,
    *,
    spread_bps: Decimal,
    slippage_bps: Decimal,
) -> Decimal:
    symbol = choice["symbol"]
    price = prices[symbol][day]
    if price <= 0 or symbol not in qty:
        return cash
    if choice["action"] == "BUY":
        requested = Decimal(choice["notional_usd"])
        shares = (requested / price).quantize(STEP, rounding=ROUND_DOWN)
        if shares <= 0:
            return cash
        spent = shares * price
        cost = _cost(spent, spread_bps, slippage_bps)
        if cash - spent - cost < RESERVE:
            return cash
        qty[symbol] += shares
        trades.append(_trade(day, symbol, "buy", shares, price, spent, spread_bps, slippage_bps))
        return cash - spent - cost
    if choice["action"] != "SELL":
        return cash
    held = qty[symbol]
    if held <= 0:
        return cash
    proceeds = held * price
    cost = _cost(proceeds, spread_bps, slippage_bps)
    qty[symbol] = Decimal("0")
    trades.append(_trade(day, symbol, "sell", held, price, proceeds, spread_bps, slippage_bps))
    return cash + proceeds - cost


def _trade(
    day: date,
    symbol: str,
    side: str,
    shares: Decimal,
    price: Decimal,
    notional: Decimal,
    spread_bps: Decimal,
    slippage_bps: Decimal,
) -> SimulatedTrade:
    spread = notional * spread_bps / Decimal("10000")
    slippage = notional * slippage_bps / Decimal("10000")
    return SimulatedTrade(
        session_date=day,
        symbol=symbol,
        side="buy" if side == "buy" else "sell",
        quantity=shares,
        price=price,
        notional=notional,
        commission=Decimal("0"),
        spread_cost=spread,
        slippage_cost=slippage,
        reason="locked_daily_rule",
    )


def _cost(notional: Decimal, spread_bps: Decimal, slippage_bps: Decimal) -> Decimal:
    return notional * (spread_bps + slippage_bps) / Decimal("10000")


def _equity(
    cash: Decimal,
    qty: dict[str, Decimal],
    prices: dict[str, dict[date, Decimal]],
    day: date,
) -> Decimal:
    market = sum((qty[symbol] * prices[symbol][day] for symbol in qty), Decimal("0"))
    return cash + market


def _folds(equity: list[EquityPoint], opening: Decimal, folds: int) -> list[Decimal]:
    sample = equity[WARMUP:]
    width = len(sample) // folds
    if width < 1:
        return []
    starts = [opening, *[sample[index * width - 1].equity for index in range(1, folds)]]
    ends = [sample[(index + 1) * width - 1].equity for index in range(folds - 1)]
    ends.append(sample[-1].equity)
    return [
        end / start - Decimal("1") for start, end in zip(starts, ends, strict=False) if start > 0
    ]


def _regimes(
    prices: dict[str, dict[date, Decimal]],
    usable: list[date],
    equity: list[EquityPoint],
) -> dict[str, Decimal]:
    buckets = {"up": Decimal("0"), "down": Decimal("0"), "unknown": Decimal("0")}
    spy = prices["SPY"]
    for index in range(WARMUP, len(usable)):
        trail = trailing_return(spy, usable[index], 20)
        key = "unknown" if trail is None else "up" if trail >= 0 else "down"
        buckets[key] += equity[index].equity - equity[index - 1].equity
    return buckets


def _hold(
    prices: dict[str, dict[date, Decimal]],
    usable: list[date],
    notional: Decimal,
    spread_bps: Decimal,
    slippage_bps: Decimal,
) -> Decimal | None:
    entry = usable[WARMUP]
    price = prices["SPY"][entry]
    if price <= 0:
        return None
    shares = (notional / price).quantize(STEP, rounding=ROUND_DOWN)
    if shares <= 0:
        return None
    spent = shares * price
    cost = _cost(spent, spread_bps, slippage_bps)
    if CAPITAL - spent - cost < 0:
        return None
    end = CAPITAL - spent - cost + shares * prices["SPY"][usable[-1]]
    return end / CAPITAL - Decimal("1")
