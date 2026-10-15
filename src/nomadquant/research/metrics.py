"""Performance statistics. Undefined values stay null."""

from decimal import Decimal
from math import sqrt

from nomadquant.research.models import EquityPoint, MetricSet, SimulatedTrade

_ZERO = Decimal("0")
_ONE = Decimal("1")
TRADING_DAYS = Decimal("252")


def compute_metrics(
    *,
    window: str,
    equity: list[EquityPoint],
    trades: list[SimulatedTrade],
    start_capital: Decimal,
    opening_equity: Decimal | None = None,
) -> MetricSet:
    unavailable: list[str] = []
    if start_capital <= 0:
        return MetricSet(
            window=window,
            start_capital=start_capital,
            end_capital=start_capital,
            gross_return=None,
            net_return=None,
            max_drawdown=None,
            annualized_volatility=None,
            sharpe=None,
            sortino=None,
            exposure=None,
            turnover=None,
            trade_count=0,
            total_costs=_ZERO,
            sample_sessions=0,
            unavailable=["non_positive_start_capital"],
        )
    if not equity:
        return MetricSet(
            window=window,
            start_capital=start_capital,
            end_capital=start_capital,
            gross_return=None,
            net_return=None,
            max_drawdown=None,
            annualized_volatility=None,
            sharpe=None,
            sortino=None,
            exposure=None,
            turnover=None,
            trade_count=0,
            total_costs=_ZERO,
            sample_sessions=0,
            unavailable=["insufficient_samples"],
        )

    end_capital = equity[-1].equity
    net_return = (end_capital / start_capital) - _ONE
    costs = sum((trade.commission + trade.spread_cost + trade.slippage_cost) for trade in trades)
    gross_return = ((end_capital + costs) / start_capital) - _ONE
    max_dd = max((point.drawdown for point in equity), default=_ZERO)

    returns = _daily_returns(
        equity, opening_equity if opening_equity is not None else start_capital
    )
    vol = _annualized_vol(returns)
    sharpe = _sharpe(returns, vol)
    sortino = _sortino(returns)
    if vol is None:
        unavailable.append("annualized_volatility")
    if sharpe is None:
        unavailable.append("sharpe")
    if sortino is None:
        unavailable.append("sortino")

    exposure = sum((point.exposure for point in equity), start=_ZERO) / Decimal(len(equity))
    traded = sum((trade.notional for trade in trades), start=_ZERO)
    turnover = traded / start_capital if start_capital > 0 else None

    return MetricSet(
        window=window,
        start_capital=start_capital,
        end_capital=end_capital,
        gross_return=gross_return,
        net_return=net_return,
        max_drawdown=max_dd,
        annualized_volatility=vol,
        sharpe=sharpe,
        sortino=sortino,
        exposure=exposure,
        turnover=turnover,
        trade_count=len(trades),
        total_costs=costs if isinstance(costs, Decimal) else Decimal(str(costs)),
        sample_sessions=len(equity),
        unavailable=unavailable,
    )


def _daily_returns(equity: list[EquityPoint], opening: Decimal) -> list[Decimal]:
    out: list[Decimal] = []
    previous = opening
    for point in equity:
        current = point.equity
        if previous > 0:
            out.append((current / previous) - _ONE)
        previous = current
    return out


def _annualized_vol(returns: list[Decimal]) -> Decimal | None:
    if len(returns) < 2:
        return None
    mean = sum(returns, start=_ZERO) / Decimal(len(returns))
    variance = sum(((item - mean) ** 2 for item in returns), start=_ZERO) / Decimal(
        len(returns) - 1
    )
    if variance <= 0:
        return _ZERO
    return Decimal(str(sqrt(float(variance)))) * Decimal(str(sqrt(float(TRADING_DAYS))))


def _sharpe(returns: list[Decimal], vol: Decimal | None) -> Decimal | None:
    if len(returns) < 2 or vol is None or vol == 0:
        return None
    mean = sum(returns, start=_ZERO) / Decimal(len(returns))
    return (mean * TRADING_DAYS) / vol


def _sortino(returns: list[Decimal]) -> Decimal | None:
    """Downside deviation versus zero, using every observation.

    Negative-only standard deviation is not used. A path with no losses is
    undefined rather than infinite.
    """
    if len(returns) < 2:
        return None
    squares = sum((min(item, _ZERO) ** 2 for item in returns), start=_ZERO)
    if squares <= 0:
        return None
    downside = Decimal(str(sqrt(float(squares / Decimal(len(returns))))))
    if downside == 0:
        return None
    annualized = downside * Decimal(str(sqrt(float(TRADING_DAYS))))
    mean = sum(returns, start=_ZERO) / Decimal(len(returns))
    return (mean * TRADING_DAYS) / annualized
