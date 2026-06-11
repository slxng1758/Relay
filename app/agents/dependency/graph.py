"""
Dependency Tracking Agent
─────────────────────────
Traverses the operational graph to map service dependencies,
detect circular chains, and score blast-radius risk.

Graph flow:
  load_graph → detect_cycles → score_risk → summarise → END
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from app.agents.state import DependencyAgentState
from app.core.database import db_session
from app.core.llm import get_llm
from app.core.logging import get_logger
from app.db.repositories.edge_repository import EdgeRepository
from app.db.models.edges import EdgeType

logger = get_logger(__name__)


# ── Node functions ─────────────────────────────────────────────────────────────

async def load_graph(state: DependencyAgentState) -> DependencyAgentState:
    """Pull dependency chain from the database."""
    service_id = state["target_service_id"]
    logger.info("dependency_agent.load_graph", service_id=service_id)

    async with db_session() as session:
        repo = EdgeRepository(session)
        chain = await repo.dependency_chain(service_id, depth=5)

    return {**state, "dependency_chain": chain}


async def detect_cycles(state: DependencyAgentState) -> DependencyAgentState:
    """Detect circular dependencies using DFS on the loaded chain."""
    chain = state.get("dependency_chain", [])

    # Build adjacency list
    adj: dict[str, list[str]] = {}
    for edge in chain:
        src, tgt = str(edge["source_id"]), str(edge["target_id"])
        adj.setdefault(src, []).append(tgt)

    visited: set[str] = set()
    rec_stack: set[str] = set()
    cycles: list[list[str]] = []

    def dfs(node: str, path: list[str]) -> None:
        visited.add(node)
        rec_stack.add(node)
        for neighbour in adj.get(node, []):
            if neighbour not in visited:
                dfs(neighbour, [*path, neighbour])
            elif neighbour in rec_stack:
                # Found a cycle
                cycle_start = path.index(neighbour)
                cycles.append(path[cycle_start:])
        rec_stack.discard(node)

    for node in list(adj.keys()):
        if node not in visited:
            dfs(node, [node])

    logger.info("dependency_agent.cycles_detected", count=len(cycles))
    return {**state, "circular_deps": cycles}


async def score_risk(state: DependencyAgentState) -> DependencyAgentState:
    """Heuristic risk score: depth + fan-in + circular penalties."""
    chain = state.get("dependency_chain", [])
    cycles = state.get("circular_deps", [])

    depth_score = min(len(chain) / 20, 1.0)            # normalise to 0-1
    cycle_penalty = min(len(cycles) * 0.25, 1.0)
    fan_in = len({str(e["target_id"]) for e in chain}) / max(len(chain), 1)

    risk = round((depth_score * 0.4 + cycle_penalty * 0.4 + fan_in * 0.2), 3)
    logger.info("dependency_agent.risk_scored", risk=risk)
    return {**state, "risk_score": risk}


async def summarise(state: DependencyAgentState) -> DependencyAgentState:
    """Ask the LLM to produce a human-readable dependency summary."""
    llm = get_llm(temperature=0.1)

    prompt = f"""You are an expert platform engineer analysing service dependencies.

Service ID: {state['target_service_id']}
Dependency chain (edges): {state.get('dependency_chain', [])}
Circular dependencies: {state.get('circular_deps', [])}
Risk score (0–1): {state.get('risk_score', 0)}

Write a concise technical summary (3–5 sentences) covering:
1. What this service depends on
2. Any circular dependency risks
3. The overall blast-radius risk and recommendations
"""
    response = await llm.ainvoke(prompt)
    return {**state, "summary": response.content}


# ── Graph assembly ─────────────────────────────────────────────────────────────

def build_dependency_graph() -> StateGraph:
    graph = StateGraph(DependencyAgentState)

    graph.add_node("load_graph", load_graph)
    graph.add_node("detect_cycles", detect_cycles)
    graph.add_node("score_risk", score_risk)
    graph.add_node("summarise", summarise)

    graph.set_entry_point("load_graph")
    graph.add_edge("load_graph", "detect_cycles")
    graph.add_edge("detect_cycles", "score_risk")
    graph.add_edge("score_risk", "summarise")
    graph.add_edge("summarise", END)

    return graph.compile()


# Singleton compiled graph
dependency_agent = build_dependency_graph()