"""Event-driven daily backtest. Offline simulation only — no broker orders."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from nomadquant.contracts import BacktestConfig, BacktestResult, Strategy, StrategyContext
from nomadquant.marketdata.availability import modeled_available_at
from nomadquant.marketdata.calendar import next_session, sessions_between
from nomadquant.research.metrics import compute_metrics
from nomadquant.research.models import (
    EquityPoint,
    ExperimentConfig,
    SimulatedDecision,
    StrategyResult,
)
from nomadquant.research.portfolio import Portfolio
from nomadquant.research.signals import momentum_return, target_from_momentum

_ZERO = Decimal("0")
_ONE = Decimal("1")


@dataclass(frozen=True)
class SessionBar:
    session_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


class DailyBacktestEngine:
    """Chronological daily simulator with next-open execution after close signals."""

    def run(self, strategy: Strategy, config: BacktestConfig) -> BacktestResult:
        """Protocol adapter. Prefer ``run_experiment_strategy`` for full evidence."""
        _ = strategy, config
        return BacktestResult(
            notes=(
                "Use nomadquant-research with an ExperimentConfig for full "
                "decision traces. The protocol adapter does not invent results."
            )
        )

    def run_experiment_strategy(
        self,
        *,
        strategy_id: str,
        config: ExperimentConfig,
        bars: dict[date, SessionBar],
        lookback: int,
        skip: int,
        mode: Literal["momentum", "buy_hold", "cash"],
    ) -> StrategyResult:
        sessions = sessions_between(config.data_start, config.data_end)
        missing = [
            session
            for session in sessions
            if session not in bars and session <= config.evaluation_end
        ]
        if missing:
            sample = ", ".join(item.isoformat() for item in missing[:5])
            raise IncompleteResearchData(
                f"Missing {len(missing)} sessions including {sample}. The experiment fails closed."
            )
        if config.adjustment != "raw" or config.research_mode != "price_only":
            raise ValueError("This engine only supports raw price-only research.")

        portfolio = Portfolio(cash=config.initial_capital_usd, costs=config.costs)
        closes = {session: bars[session].close for session in sessions if session in bars}
        pending_weight: Decimal | None = None
        pending_reason = ""
        pending_decision_date: date | None = None
        pending_features: dict[str, str] = {}
        buy_hold_done = False
        trades = []
        decisions: list[SimulatedDecision] = []
        equity_points: list[EquityPoint] = []
        peak = config.initial_capital_usd

        eval_sessions = [
            session
            for session in sessions
            if config.evaluation_start <= session <= config.evaluation_end
        ]
        for session in eval_sessions:
            bar = bars[session]
            prices = {config.symbols[0]: bar.open}

            if pending_weight is not None and pending_decision_date is not None:
                before = portfolio.snapshot(prices)
                trade = portfolio.rebalance_to_weight(
                    symbol=config.symbols[0],
                    target_weight=pending_weight,
                    price=bar.open,
                    session_date=session,
                    reason=pending_reason,
                )
                after = portfolio.snapshot(prices)
                if trade is not None:
                    trades.append(trade)
                    action: Literal["buy", "sell", "hold", "reject", "no_trade"] = trade.side
                elif pending_weight == portfolio.exposure(prices):
                    action = "hold"
                else:
                    action = "no_trade"
                decisions.append(
                    SimulatedDecision(
                        session_date=pending_decision_date,
                        decision_timestamp=modeled_available_at(pending_decision_date).isoformat(),
                        data_cutoff=modeled_available_at(pending_decision_date).isoformat(),
                        symbol=config.symbols[0],
                        signal=pending_reason,
                        feature_inputs=pending_features,
                        proposed_target_weight=pending_weight,
                        action=action,
                        rationale=(
                            f"Signal used completed close on {pending_decision_date.isoformat()}; "
                            f"simulated fill at open on {session.isoformat()}."
                        ),
                        evidence_hash=_evidence_hash(
                            pending_decision_date, pending_features, pending_weight
                        ),
                        fill_session=session,
                        fill_price=None if trade is None else trade.price,
                        portfolio_before=before,
                        portfolio_after=after,
                        warnings=[
                            "Simulated backtest decision. Not an Alpaca paper order.",
                            "Price-only research. Dividends are not included.",
                        ],
                    )
                )
                pending_weight = None
                pending_reason = ""
                pending_decision_date = None
                pending_features = {}

            if mode == "cash":
                pass
            elif mode == "buy_hold":
                if not buy_hold_done and session == eval_sessions[0]:
                    # Entry at the first evaluation open. Does not use that day's close.
                    before = portfolio.snapshot(prices)
                    trade = portfolio.rebalance_to_weight(
                        symbol=config.symbols[0],
                        target_weight=_ONE,
                        price=bar.open,
                        session_date=session,
                        reason="buy_hold_entry",
                    )
                    after = portfolio.snapshot(prices)
                    if trade is not None:
                        trades.append(trade)
                    decisions.append(
                        SimulatedDecision(
                            session_date=session,
                            decision_timestamp=bar_open_timestamp(session),
                            data_cutoff=bar_open_timestamp(session),
                            symbol=config.symbols[0],
                            signal="buy_hold_entry",
                            feature_inputs={"mode": "buy_hold"},
                            proposed_target_weight=_ONE,
                            action="buy" if trade is not None else "no_trade",
                            rationale=(
                                "Buy-and-hold enters at the first evaluation open. "
                                "It does not use that session's close."
                            ),
                            evidence_hash=_evidence_hash(session, {"mode": "buy_hold"}, _ONE),
                            fill_session=session,
                            fill_price=None if trade is None else trade.price,
                            portfolio_before=before,
                            portfolio_after=after,
                            warnings=[
                                "Simulated backtest decision. Not an Alpaca paper order.",
                            ],
                        )
                    )
                    buy_hold_done = True
            elif mode == "momentum" and _is_month_start(session, sessions):
                value = momentum_return(closes, sessions, session, lookback, skip)
                target = target_from_momentum(value)
                pending_weight = target
                pending_reason = "tsmom_rebalance"
                pending_decision_date = session
                pending_features = {
                    "lookback_sessions": str(lookback),
                    "skip_sessions": str(skip),
                    "momentum_return": "null" if value is None else str(value),
                    "close": str(bar.close),
                    "information_cutoff": modeled_available_at(session).isoformat(),
                }

            close_prices = {config.symbols[0]: bar.close}
            equity = portfolio.market_value(close_prices)
            peak = max(peak, equity)
            drawdown = _ZERO if peak <= 0 else (peak - equity) / peak
            equity_points.append(
                EquityPoint(
                    session_date=session,
                    equity=equity,
                    cash=portfolio.cash,
                    exposure=portfolio.exposure(close_prices),
                    drawdown=drawdown,
                    window=_window_name(session, config),
                )
            )
            if portfolio.cash < 0:
                raise RuntimeError("Cash became negative.")
            if any(qty < 0 for qty in portfolio.positions.values()):
                raise RuntimeError("Short exposure is not allowed.")

        metrics = []
        for name in ("train", "validation", "test", "full"):
            slice_points = [point for point in equity_points if _in_window(point, name, config)]
            if name == "full":
                slice_points = equity_points
            if not slice_points:
                continue
            start_cap = slice_points[0].equity
            slice_trades = [
                trade
                for trade in trades
                if slice_points[0].session_date
                <= trade.session_date
                <= slice_points[-1].session_date
            ]
            metrics.append(
                compute_metrics(
                    window=name,
                    equity=slice_points,
                    trades=slice_trades,
                    start_capital=start_cap,
                )
            )
        return StrategyResult(
            strategy_id=strategy_id,
            metrics=metrics,
            equity=equity_points,
            trades=trades,
            decisions=decisions,
        )


class IncompleteResearchData(RuntimeError):
    """Raised when required bars are missing. Fail closed."""


def bar_open_timestamp(session: date) -> str:
    return datetime(session.year, session.month, session.day, 9, 30).isoformat() + "-05:00"


def _is_month_start(session: date, sessions: list[date]) -> bool:
    prior = [item for item in sessions if item < session]
    if not prior:
        return True
    return prior[-1].month != session.month


def _window_name(session: date, config: ExperimentConfig) -> str:
    windows = config.windows
    if windows.train_start <= session <= windows.train_end:
        return "train"
    if windows.validation_start <= session <= windows.validation_end:
        return "validation"
    if windows.test_start <= session <= windows.test_end:
        return "test"
    return "other"


def _in_window(point: EquityPoint, name: str, config: ExperimentConfig) -> bool:
    if name == "full":
        return True
    return point.window == name


def _evidence_hash(session: date, features: dict[str, str], weight: Decimal) -> str:
    payload = json.dumps(
        {"session": session.isoformat(), "features": features, "weight": str(weight)},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# Silence unused import if StrategyContext is reserved for future adapter paths.
_ = StrategyContext, next_session
