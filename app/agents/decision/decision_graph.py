"""
Decision Reconstruction Agent
──────────────────────────────
Given a natural-language query, retrieves related decisions from the graph,
reconstructs their context (who made them, what they superseded),
and synthesises a coherent answer with a timeline.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.agents.state import DecisionResult
from app.core.database import db_session
from app.core.llm import complete
from app.core.logging import get_logger
from app.db.models.edges import EdgeType
from app.db.models.nodes import Decision
from app.db.repositories.edge_repository import EdgeRepository

logger = get_logger(__name__)


async def _retrieve(query: str) -> list[str]:
    from app.memory.retrieval.retriever import HybridRetriever
    results = await HybridRetriever().search(query=query, node_types=["decision"], top_k=10)
    return [r["node_id"] for r in results]


async def _enrich(candidate_ids: list[str]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    async with db_session() as session:
        edge_repo = EdgeRepository(session)
        for decision_id in candidate_ids[:8]:
            row = await session.execute(select(Decision).where(Decision.id == decision_id))
            decision = row.scalar_one_or_none()
            if not decision:
                continue
            outgoing = await edge_repo.get_outgoing(decision_id)
            incoming = await edge_repo.get_incoming(decision_id)
            enriched.append({
                "id": str(decision.id),
                "title": decision.title,
                "summary": decision.summary,
                "status": decision.status,
                "decided_at": decision.decided_at.isoformat() if decision.decided_at else None,
                "source_url": decision.source_url,
                "outgoing_edges": [
                    {"type": e.edge_type, "target_id": str(e.target_id), "target_type": e.target_type}
                    for e in outgoing
                ],
                "incoming_edges": [
                    {"type": e.edge_type, "source_id": str(e.source_id), "source_type": e.source_type}
                    for e in incoming
                ],
            })
    return enriched


def _build_timeline(enriched: list[dict[str, Any]]) -> list[dict[str, Any]]:
    timeline = sorted(enriched, key=lambda d: d.get("decided_at") or "0000")
    for d in timeline:
        d["superseded_by"] = [
            e["source_id"]
            for e in d.get("incoming_edges", [])
            if e["type"] == EdgeType.SUPERSEDES
        ]
    return timeline


async def _answer(query: str, timeline: list[dict[str, Any]]) -> str:
    timeline_text = "\n\n".join(
        f"[{d.get('decided_at', 'unknown date')}] {d['title']}\n"
        f"  Status: {d['status']}\n"
        f"  Summary: {d.get('summary', 'N/A')}\n"
        f"  Superseded by: {', '.join(d.get('superseded_by', [])) or 'none'}"
        for d in timeline
    )
    prompt = f"""You are an engineering knowledge assistant helping reconstruct decision history.

User query: {query}

Decision timeline (chronological):
{timeline_text or 'No decisions found matching this query.'}

Provide a clear, concise answer (4–6 sentences) that:
1. Directly answers the user's question
2. Highlights the most relevant decisions and their current status
3. Notes any decisions that were superseded or reversed
4. Flags unresolved or open decisions that may need attention
"""
    return await complete(prompt, temperature=0.2)


async def run_decision_agent(query: str) -> DecisionResult:
    logger.info("decision_agent.start", query=query)
    candidate_ids = await _retrieve(query)
    enriched = await _enrich(candidate_ids)
    timeline = _build_timeline(enriched)
    answer = await _answer(query, timeline)
    logger.info("decision_agent.done", decisions_found=len(timeline))
    return DecisionResult(answer=answer, decision_timeline=timeline)
