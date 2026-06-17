"""
Return types for each specialist agent.
Simple dataclasses — no framework dependency.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DependencyResult:
    dependency_chain: list[dict[str, Any]] = field(default_factory=list)
    circular_deps: list[list[str]] = field(default_factory=list)
    risk_score: float = 0.0
    summary: str = ""


@dataclass
class DecisionResult:
    answer: str = ""
    decision_timeline: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RiskResult:
    risk_items: list[dict[str, Any]] = field(default_factory=list)
    report: str = ""


@dataclass
class OnboardingResult:
    final_document: str = ""
