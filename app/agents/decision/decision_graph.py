"""
Decision Reconstruction Agent
──────────────────────────────
Given a natural-language query, retrieves related decisions from the graph,
reconstructs their context (who made them, what they blocked / superseded),
and synthesises a coherent answer with a timeline.

Graph flow:
  retrieve_decisions → enrich_context → build_timeline → answer → END
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph
from sqlalchemy import select

from app.agents.state import DecisionAgentState
from app.core.database import db_session
from app.core.llm import get_llm
from app.core.logging import get_logger
from app.db.models.nodes import Decision
from app.db.repositories.edge_repository import EdgeRepository
from app.db.models.edges import EdgeType

logger = get_logger(__name__)


async def retrieve_decisions(state: DecisionAgentState) -> DecisionAgentState:
    """Semantic search over decision embeddings, fallback to keyword match."""
    from app.memory.retrieval.retriever import HybridRetriever

    retriever = HybridRetriever()
    results = await retriever.search(
        query=state["query"],
        node_types=["decision"],
        top_k=10,
    )
    candidate_ids = [r["node_id"] for r in results]
    logger.info("decision_agent.retrieved", count=len(candidate_ids))
    return {**state, "candidate_decision_ids": candidate_ids}


async def enrich_context(state: DecisionAgentState) -> DecisionAgentState:
    """For each candidate decision, load edges (who decided, what it supersedes)."""
    candidate_ids = state.get("candidate_decision_ids", [])
    enriched: list[dict[str, Any]] = []

    async with db_session() as session:
        edge_repo = EdgeRepository(session)

        for decision_id in candidate_ids[:8]:  # cap at 8 to stay in context budget
            result = await session.execute(
                select(Decision).where(Decision.id == decision_id)
            )
            decision = result.scalar_one_or_none()
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

    return {**state, "reconstructed_context": enriched}


async def build_timeline(state: DecisionAgentState) -> DecisionAgentState:
    """Sort decisions chronologically and mark supersession chains."""
    context = state.get("reconstructed_context", [])
    sorted_decisions = sorted(
        context,
        key=lambda d: d.get("decided_at") or "0000",
    )

    # Mark which decisions supersede others
    for d in sorted_decisions:
        d["superseded_by"] = [
            e["source_id"]
            for e in d.get("incoming_edges", [])
            if e["type"] == EdgeType.SUPERSEDES
        ]

    return {**state, "decision_timeline": sorted_decisions}


async def answer(state: DecisionAgentState) -> DecisionAgentState:
    """Use the LLM to synthesise a coherent answer from the timeline."""
    llm = get_llm(temperature=0.2)

    timeline_text = "\n\n".join(
        f"[{d.get('decided_at', 'unknown date')}] {d['title']}\n"
        f"  Status: {d['status']}\n"
        f"  Summary: {d.get('summary', 'N/A')}\n"
        f"  Superseded by: {', '.join(d.get('superseded_by', [])) or 'none'}"
        for d in state.get("decision_timeline", [])
    )

    prompt = f"""You are an engineering knowledge assistant helping reconstruct decision history.

User query: {state['query']}

Decision timeline (chronological):
{timeline_text or 'No decisions found matching this query.'}

Provide a clear, concise answer (4–6 sentences) that:
1. Directly answers the user's question
2. Highlights the most relevant decisions and their current status
3. Notes any decisions that were superseded or reversed
4. Flags unresolved or open decisions that may need attention
"""
    response = await llm.ainvoke(prompt)
    return {**state, "answer": response.content}


def build_decision_graph() -> StateGraph:
    graph = StateGraph(DecisionAgentState)

    graph.add_node("retrieve_decisions", retrieve_decisions)
    graph.add_node("enrich_context", enrich_context)
    graph.add_node("build_timeline", build_timeline)
    graph.add_node("answer", answer)

    graph.set_entry_point("retrieve_decisions")
    graph.add_edge("retrieve_decisions", "enrich_context")
    graph.add_edge("enrich_context", "build_timeline")
    graph.add_edge("build_timeline", "answer")
    graph.add_edge("answer", END)

    return graph.compile()


decision_agent = build_decision_graph()