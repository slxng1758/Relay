"""Request/response schemas for the agent-trigger endpoints in app/api/routes/agents.py."""
from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel


# ── Dependency agent ──────────────────────────────────────────────────────────

class DependencyRequest(BaseModel):
    service_id: uuid.UUID


class DependencyResponse(BaseModel):
    service_id: uuid.UUID
    dependency_chain: list[dict[str, Any]]
    circular_deps: list[list[str]]
    risk_score: float
    summary: str
    run_id: str


# ── Decision agent ───────────────────────────────────────────────────────────

class DecisionQueryRequest(BaseModel):
    query: str


class DecisionQueryResponse(BaseModel):
    query: str
    answer: str
    decision_timeline: list[dict[str, Any]]
    run_id: str


# ── Risk agent ───────────────────────────────────────────────────────────────

class RiskRequest(BaseModel):
    scope: Literal["team", "service", "global"]
    scope_id: uuid.UUID | None = None


class RiskResponse(BaseModel):
    scope: str
    risk_items: list[dict[str, Any]]
    report: str
    run_id: str


# ── Onboarding agent ─────────────────────────────────────────────────────────

class OnboardingRequest(BaseModel):
    person_id: uuid.UUID
    team_id: uuid.UUID
    doc_type: Literal["onboarding", "handoff"] = "onboarding"


class OnboardingResponse(BaseModel):
    person_id: uuid.UUID
    team_id: uuid.UUID
    doc_type: str
    document: str
    run_id: str
