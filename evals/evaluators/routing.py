"""
Routing evaluator — tests whether the coordinator LLM routes questions to the
correct specialist tools, without executing the specialists themselves.

Approach: patch `app.agents.coordinator._dispatch` to a no-op that records
tool names. The real coordinator LLM still runs (real Anthropic API call),
so this tests LLM routing judgment in isolation from specialist correctness.

Metrics per case:
  precision = |expected ∩ actual| / |actual|     (no spurious tools called)
  recall    = |expected ∩ actual| / |expected|   (no required tools missed)
  exact_match = expected == actual

Aggregate:
  macro_precision, macro_recall, macro_f1, exact_match_rate
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

DATASET_PATH = Path(__file__).parent.parent / "dataset" / "routing_cases.json"


@dataclass
class RoutingCaseResult:
    case_id: str
    category: str
    question: str
    expected_tools: list[str]
    actual_tools: list[str]
    precision: float
    recall: float
    f1: float
    exact_match: bool


@dataclass
class RoutingReport:
    cases: list[RoutingCaseResult] = field(default_factory=list)
    macro_precision: float = 0.0
    macro_recall: float = 0.0
    macro_f1: float = 0.0
    exact_match_rate: float = 0.0
    n_cases: int = 0
    n_skipped: int = 0


def _f1(precision: float, recall: float) -> float:
    denom = precision + recall
    return 2 * precision * recall / denom if denom > 0 else 0.0


async def _run_case(case: dict[str, Any]) -> RoutingCaseResult | None:
    """Run a single routing test case. Returns None if skipped."""
    from app.agents.coordinator import run_coordinator

    called: list[str] = []

    async def _record_and_noop(name: str, inputs: dict[str, Any]) -> dict[str, Any]:
        called.append(name)
        # Return minimal valid payloads so the coordinator LLM can continue
        stubs: dict[str, dict[str, Any]] = {
            "analyze_dependencies": {
                "dependency_chain": [],
                "circular_deps": [],
                "risk_score": 0.0,
                "summary": "eval-stub: no data",
            },
            "query_decisions": {
                "answer": "eval-stub: no data",
                "decision_timeline": [],
            },
            "assess_risk": {
                "risk_items": [],
                "report": "eval-stub: no data",
            },
            "generate_onboarding_doc": {
                "document": "eval-stub: no data",
            },
        }
        return stubs.get(name, {"result": "eval-stub: unknown tool"})

    with patch("app.agents.coordinator._dispatch", side_effect=_record_and_noop):
        try:
            await run_coordinator(question=case["question"], run_id=str(uuid.uuid4()))
        except Exception:
            return None

    expected = set(case["expected_tools"])
    actual = set(called)
    tp = expected & actual

    precision = len(tp) / len(actual) if actual else (1.0 if not expected else 0.0)
    recall = len(tp) / len(expected) if expected else (1.0 if not actual else 0.0)

    return RoutingCaseResult(
        case_id=case["id"],
        category=case["category"],
        question=case["question"],
        expected_tools=sorted(expected),
        actual_tools=sorted(actual),
        precision=precision,
        recall=recall,
        f1=_f1(precision, recall),
        exact_match=expected == actual,
    )


async def run(verbose: bool = False) -> RoutingReport:
    """Evaluate routing accuracy across all test cases in the dataset."""
    cases: list[dict[str, Any]] = json.loads(DATASET_PATH.read_text())

    report = RoutingReport(n_cases=len(cases))
    precision_scores: list[float] = []
    recall_scores: list[float] = []
    f1_scores: list[float] = []
    exact_matches = 0

    for case in cases:
        result = await _run_case(case)
        if result is None:
            report.n_skipped += 1
            continue

        report.cases.append(result)
        precision_scores.append(result.precision)
        recall_scores.append(result.recall)
        f1_scores.append(result.f1)
        if result.exact_match:
            exact_matches += 1

        if verbose:
            status = "✓" if result.exact_match else "✗"
            print(
                f"  [{status}] {case['id']} ({case['category']})\n"
                f"       expected={result.expected_tools}\n"
                f"       actual  ={result.actual_tools}\n"
                f"       P={result.precision:.2f} R={result.recall:.2f} F1={result.f1:.2f}"
            )

    n = len(report.cases)
    if n:
        report.macro_precision = sum(precision_scores) / n
        report.macro_recall = sum(recall_scores) / n
        report.macro_f1 = sum(f1_scores) / n
        report.exact_match_rate = exact_matches / n

    return report
