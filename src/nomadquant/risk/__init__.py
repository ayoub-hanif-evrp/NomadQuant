"""Phase 5A deterministic risk engine.

Independent of any broker. Nothing in this package imports Alpaca, submits
orders, or reads Alpaca paper equity. Every evaluation runs against a
separate internal $100 ledger (``Settings.initial_virtual_capital_usd``),
never against a broker account.

``RiskEngine.evaluate`` is hypothetical only: it never mutates the
``InternalLedger`` it is given and never mutates any broker or internal cash
balance. A verdict is advice for a future order gateway, which does not exist
yet in this codebase.
"""

from nomadquant.risk.engine import RiskEngine, evaluate_proposal
from nomadquant.risk.ledger import InternalLedger
from nomadquant.risk.policy import ALLOWED_SYMBOLS, POLICY_VERSION, RiskPolicy
from nomadquant.risk.schemas import EvaluationResult, PriceQuote, Proposal, RuleVerdict
from nomadquant.risk.store import RiskStore, RiskStoreError

__all__ = [
    "ALLOWED_SYMBOLS",
    "POLICY_VERSION",
    "EvaluationResult",
    "InternalLedger",
    "PriceQuote",
    "Proposal",
    "RiskEngine",
    "RiskPolicy",
    "RiskStore",
    "RiskStoreError",
    "RuleVerdict",
    "evaluate_proposal",
]
