"""
Dependency Tracking Agent
─────────────────────────
Traverses the operational graph to map service dependencies,
detect circular chains, and score blast-radius risk.
"""
from __future__ import annotations

from typing import Any

from app.agents.state import DependencyResult
from app.core.database import db_session
from app.core.llm import complete
from app.core.logging import get_logger
from app.db.models.edges import EdgeType
from app.db.repositories.edge_repository import EdgeRepository

logger = get_logger(__name__)


async def _load_graph(service_id: str) -> list[dict[str, Any]]:
    async with db_session() as session:
        return await EdgeRepository(session).dependency_chain(service_id, depth=5)


def _detect_cycles(chain: list[dict[str, Any]]) -> list[list[str]]:
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
                cycles.append(path[path.index(neighbour):])
        rec_stack.discard(node)

    for node in list(adj):
        if node not in visited:
            dfs(node, [node])

    return cycles


def _score_risk(chain: list[dict[str, Any]], cycles: list[list[str]]) -> float:
    depth_score = min(len(chain) / 20, 1.0)
    cycle_penalty = min(len(cycles) * 0.25, 1.0)
    fan_in = len({str(e["target_id"]) for e in chain}) / max(len(chain), 1)
    return round(depth_score * 0.4 + cycle_penalty * 0.4 + fan_in * 0.2, 3)


async def _summarise(
    service_id: str,
    chain: list[dict[str, Any]],
    cycles: list[list[str]],
    risk_score: float,
) -> str:
    prompt = f"""You are an expert platform engineer analysing service dependencies.

Service ID: {service_id}
Dependency chain (edges): {chain}
Circular dependencies: {cycles}
Risk score (0–1): {risk_score}

Write a concise technical summary (3–5 sentences) covering:
1. What this service depends on
2. Any circular dependency risks
3. The overall blast-radius risk and recommendations
"""
    return await complete(prompt, temperature=0.1)


async def run_dependency_agent(service_id: str) -> DependencyResult:
    logger.info("dependency_agent.start", service_id=service_id)
    chain = await _load_graph(service_id)
    cycles = _detect_cycles(chain)
    risk_score = _score_risk(chain, cycles)
    summary = await _summarise(service_id, chain, cycles, risk_score)
    logger.info("dependency_agent.done", service_id=service_id, risk_score=risk_score)
    return DependencyResult(
        dependency_chain=chain,
        circular_deps=cycles,
        risk_score=risk_score,
        summary=summary,
    )
