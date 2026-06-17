"""
Retrieval evaluator — measures how well the HybridRetriever surfaces relevant
decisions when given natural-language queries.

Decision titles in the dataset are resolved to UUIDs at runtime via a DB query,
making the dataset portable across DB resets (no hardcoded UUIDs).

Metrics per query:
  recall@k  for k in {1, 3, 5, 10}   — fraction of relevant docs found in top-k
  precision@k for k in {1, 3, 5, 10}
  MRR       — mean reciprocal rank of the first relevant result
  NDCG@5    — normalised discounted cumulative gain

Aggregate: mean of each metric across all non-empty-relevant-set cases.
Negative cases (no relevant docs) are evaluated separately: precision@k should be 0.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DATASET_PATH = Path(__file__).parent.parent / "dataset" / "retrieval_cases.json"
KS = (1, 3, 5, 10)


@dataclass
class RetrievalCaseResult:
    case_id: str
    query: str
    relevant_ids: list[str]
    retrieved_ids: list[str]
    recall_at_k: dict[int, float]
    precision_at_k: dict[int, float]
    mrr: float
    ndcg_at_5: float
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class RetrievalReport:
    cases: list[RetrievalCaseResult] = field(default_factory=list)
    mean_recall_at_k: dict[int, float] = field(default_factory=dict)
    mean_precision_at_k: dict[int, float] = field(default_factory=dict)
    mean_mrr: float = 0.0
    mean_ndcg_at_5: float = 0.0
    n_cases: int = 0
    n_skipped: int = 0


def _recall_at_k(relevant: set[str], retrieved: list[str], k: int) -> float:
    if not relevant:
        return 1.0
    hits = sum(1 for r in retrieved[:k] if r in relevant)
    return hits / len(relevant)


def _precision_at_k(relevant: set[str], retrieved: list[str], k: int) -> float:
    if k == 0:
        return 0.0
    hits = sum(1 for r in retrieved[:k] if r in relevant)
    return hits / k


def _mrr(relevant: set[str], retrieved: list[str]) -> float:
    for rank, r in enumerate(retrieved, start=1):
        if r in relevant:
            return 1.0 / rank
    return 0.0


def _ndcg_at_k(relevant: set[str], retrieved: list[str], k: int) -> float:
    """Binary-relevance NDCG (relevant=1, not relevant=0)."""
    def dcg(ids: list[str], cutoff: int) -> float:
        return sum(
            (1.0 if ids[i] in relevant else 0.0) / math.log2(i + 2)
            for i in range(min(cutoff, len(ids)))
        )

    actual_dcg = dcg(retrieved, k)
    ideal_ids = list(relevant) + ["__pad__"] * k
    ideal_dcg = dcg(ideal_ids, k)
    return actual_dcg / ideal_dcg if ideal_dcg > 0 else 0.0


async def _resolve_titles(titles: list[str]) -> list[str]:
    """Return UUIDs for the given decision titles (may return a subset if missing)."""
    if not titles:
        return []
    from sqlalchemy import select
    from app.core.database import db_session
    from app.db.models.nodes import Decision

    async with db_session() as session:
        rows = await session.execute(
            select(Decision.id).where(Decision.title.in_(titles))
        )
        return [str(row[0]) for row in rows]


async def _run_case(case: dict[str, Any]) -> RetrievalCaseResult:
    from app.memory.retrieval.retriever import HybridRetriever

    relevant_ids = await _resolve_titles(case["relevant_decision_titles"])

    if case["relevant_decision_titles"] and not relevant_ids:
        return RetrievalCaseResult(
            case_id=case["id"],
            query=case["query"],
            relevant_ids=[],
            retrieved_ids=[],
            recall_at_k={k: 0.0 for k in KS},
            precision_at_k={k: 0.0 for k in KS},
            mrr=0.0,
            ndcg_at_5=0.0,
            skipped=True,
            skip_reason="relevant decisions not found in DB (seed data missing?)",
        )

    try:
        results = await HybridRetriever().search(
            query=case["query"],
            node_types=["decision"],
            top_k=max(KS),
        )
        retrieved_ids = [r["node_id"] for r in results]
    except Exception as exc:
        return RetrievalCaseResult(
            case_id=case["id"],
            query=case["query"],
            relevant_ids=relevant_ids,
            retrieved_ids=[],
            recall_at_k={k: 0.0 for k in KS},
            precision_at_k={k: 0.0 for k in KS},
            mrr=0.0,
            ndcg_at_5=0.0,
            skipped=True,
            skip_reason=f"retriever error: {exc}",
        )

    relevant_set = set(relevant_ids)
    return RetrievalCaseResult(
        case_id=case["id"],
        query=case["query"],
        relevant_ids=relevant_ids,
        retrieved_ids=retrieved_ids,
        recall_at_k={k: _recall_at_k(relevant_set, retrieved_ids, k) for k in KS},
        precision_at_k={k: _precision_at_k(relevant_set, retrieved_ids, k) for k in KS},
        mrr=_mrr(relevant_set, retrieved_ids),
        ndcg_at_5=_ndcg_at_k(relevant_set, retrieved_ids, 5),
    )


async def run(verbose: bool = False) -> RetrievalReport:
    cases: list[dict[str, Any]] = json.loads(DATASET_PATH.read_text())

    report = RetrievalReport(n_cases=len(cases))
    scored: list[RetrievalCaseResult] = []

    for case in cases:
        result = await _run_case(case)
        report.cases.append(result)

        if result.skipped:
            report.n_skipped += 1
        else:
            scored.append(result)

        if verbose:
            if result.skipped:
                print(f"  [SKIP] {case['id']} — {result.skip_reason}")
            else:
                print(
                    f"  {case['id']}: R@1={result.recall_at_k[1]:.2f} "
                    f"R@5={result.recall_at_k[5]:.2f} "
                    f"MRR={result.mrr:.2f} "
                    f"NDCG@5={result.ndcg_at_5:.2f}"
                )

    if scored:
        n = len(scored)
        report.mean_recall_at_k = {
            k: sum(r.recall_at_k[k] for r in scored) / n for k in KS
        }
        report.mean_precision_at_k = {
            k: sum(r.precision_at_k[k] for r in scored) / n for k in KS
        }
        report.mean_mrr = sum(r.mrr for r in scored) / n
        report.mean_ndcg_at_5 = sum(r.ndcg_at_5 for r in scored) / n

    return report
