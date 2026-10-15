"""Phase 4A local AI research agents.

ENGINE: local Ollama only (loopback). Agents run a retrospective Researcher ->
Skeptic -> Reviewer review of stored backtests through read-only research
tools. They never place orders, never receive broker credentials, and their
output is not a trading decision. TRADING_MODE stays paper.
"""

from nomadquant.agents.claims import CLAIM_NAMES, TOLERANCE, verify_claims
from nomadquant.agents.constants import PROMPT_VERSION, RUN_LABEL, TOOL_SCHEMA_VERSION
from nomadquant.agents.guarded_tools import (
    ALLOWED_TOOLS,
    FORBIDDEN_TOOLS,
    GuardedResearchTools,
    GuardedToolError,
    ToolBudgetExceeded,
)
from nomadquant.agents.ollama import (
    OllamaError,
    OllamaProvider,
    OllamaResponseError,
    OllamaUnavailableError,
)
from nomadquant.agents.schemas import (
    Claim,
    Objection,
    ResearcherReport,
    ReviewerReport,
    SkepticReport,
)
from nomadquant.agents.store import AgentStore, AgentStoreError
from nomadquant.agents.workflow import run_research_review

__all__ = [
    "ALLOWED_TOOLS",
    "CLAIM_NAMES",
    "FORBIDDEN_TOOLS",
    "PROMPT_VERSION",
    "RUN_LABEL",
    "TOLERANCE",
    "TOOL_SCHEMA_VERSION",
    "AgentStore",
    "AgentStoreError",
    "Claim",
    "GuardedResearchTools",
    "GuardedToolError",
    "Objection",
    "OllamaError",
    "OllamaProvider",
    "OllamaResponseError",
    "OllamaUnavailableError",
    "ResearcherReport",
    "ReviewerReport",
    "SkepticReport",
    "ToolBudgetExceeded",
    "run_research_review",
    "verify_claims",
]
