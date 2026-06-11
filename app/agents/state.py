"""
Shared LangGraph state schemas.
All agents use TypedDict state so the graph can be typed end-to-end.
"""
from __future__ import annotations

import uuid
from typing import Any, Annotated
from typing_extensions import TypedDict

from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


# ── Base operational state ────────────────────────────────────────────────────

class BaseAgentState(TypedDict, total=False):
    """Minimal state every agent graph shares."""
    run_id: str                          # UUID for this agent run
    messages: Annotated[list[BaseMessage], add_messages]
    error: str | None
    metadata: dict[str, Any]


# ── Dependency agent state ────────────────────────────────────────────────────

class DependencyAgentState(BaseAgentState, total=False):
    target_service_id: str              # UUID of the service to analyse
    dependency_chain: list[dict[str, Any]]
    circular_deps: list[list[str]]
    risk_score: float
    summary: str


# ── Decision agent state ──────────────────────────────────────────────────────

class DecisionAgentState(BaseAgentState, total=False):
    query: str                          # Natural language question
    candidate_decision_ids: list[str]
    reconstructed_context: list[dict[str, Any]]
    decision_timeline: list[dict[str, Any]]
    answer: str


# ── Risk agent state ──────────────────────────────────────────────────────────

class RiskAgentState(BaseAgentState, total=False):
    scope: str                          # "team" | "service" | "global"
    scope_id: str | None
    signals: list[dict[str, Any]]       # raw risk signals collected
    risk_items: list[dict[str, Any]]    # structured {risk, severity, recommendation}
    report: str


# ── Onboarding agent state ────────────────────────────────────────────────────

class OnboardingAgentState(BaseAgentState, total=False):
    person_id: str
    team_id: str
    doc_type: str                       # "onboarding" | "handoff"
    context_nodes: list[dict[str, Any]]
    draft: str
    final_document: str