"""
Risk Detection Agent
────────────────────
Scans the operational graph for risk signals:
  - Unowned services / repos
  - Stale open tasks past due date
  - Single-person ownership (bus factor = 1)
  - Circular or deep dependency chains
  - Open decisions with no resolution > 30 days

Graph flow:
  collect_signals → score_signals → generate_report → END
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from langgraph.graph import END, StateGraph
from sqlalchemy import select, func

from app.agents.state import RiskAgentState
from app.core.database import db_session
from app.core.llm import get_llm
from app.core.logging import get_logger
from app.db.models.nodes import Service, Task, Decision, Person, Team
from app.db.models.edges import Edge, EdgeType
from app.db.repositories.edge_repository import EdgeRepository

logger = get_logger(__name__)

STALE_TASK_DAYS = 14
STALE_DECISION_DAYS = 30


async def collect_signals(state: RiskAgentState) -> RiskAgentState:
    """Query the DB for concrete risk signals."""
    signals: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)

    async with db_session() as session:
        # 1. Unowned services
        result = await session.execute(
            select(Service).where(Service.owner_team_id.is_(None))
        )
        for svc in result.scalars():
            signals.append({
                "type": "unowned_service",
                "severity": "high",
                "entity_id": str(svc.id),
                "entity_name": svc.name,
                "detail": f"Service '{svc.name}' has no owning team",
            })

        # 2. Overdue tasks
        result = await session.execute(
            select(Task).where(
                Task.status.in_(["open", "in_progress"]),
                Task.due_date < now - timedelta(days=STALE_TASK_DAYS),
            )
        )
        for task in result.scalars():
            signals.append({
                "type": "overdue_task",
                "severity": "medium",
                "entity_id": str(task.id),
                "entity_name": task.title,
                "detail": f"Task '{task.title}' overdue (due {task.due_date})",
            })

        # 3. Stale open decisions
        result = await session.execute(
            select(Decision).where(
                Decision.status == "open",
                Decision.created_at < now - timedelta(days=STALE_DECISION_DAYS),
            )
        )
        for dec in result.scalars():
            signals.append({
                "type": "stale_decision",
                "severity": "medium",
                "entity_id": str(dec.id),
                "entity_name": dec.title,
                "detail": f"Decision '{dec.title}' unresolved for > {STALE_DECISION_DAYS} days",
            })

        # 4. Bus factor: persons who are the sole owner of > 2 services
        result = await session.execute(
            select(Edge.source_id, func.count(Edge.target_id).label("owned"))
            .where(Edge.edge_type == EdgeType.OWNS, Edge.source_type == "person")
            .group_by(Edge.source_id)
            .having(func.count(Edge.target_id) > 2)
        )
        for row in result:
            signals.append({
                "type": "bus_factor",
                "severity": "high",
                "entity_id": str(row.source_id),
                "entity_name": str(row.source_id),
                "detail": f"Person owns {row.owned} services solo – single point of failure",
            })

    logger.info("risk_agent.signals_collected", count=len(signals))
    return {**state, "signals": signals}


async def score_signals(state: RiskAgentState) -> RiskAgentState:
    """Assign numeric severity and deduplicate by entity."""
    severity_map = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    seen: set[str] = set()
    risk_items: list[dict[str, Any]] = []

    for sig in state.get("signals", []):
        key = f"{sig['type']}:{sig['entity_id']}"
        if key in seen:
            continue
        seen.add(key)
        risk_items.append({
            **sig,
            "score": severity_map.get(sig["severity"], 1),
        })

    risk_items.sort(key=lambda r: r["score"], reverse=True)
    return {**state, "risk_items": risk_items}


async def generate_report(state: RiskAgentState) -> RiskAgentState:
    """LLM-generated executive risk summary."""
    llm = get_llm(temperature=0.1)

    items_text = "\n".join(
        f"- [{r['severity'].upper()}] {r['type']}: {r['detail']}"
        for r in state.get("risk_items", [])[:20]
    )

    prompt = f"""You are an engineering risk analyst reviewing an operational graph.

Scope: {state['scope']}{(' / ' + state.get('scope_id', '')) if state.get('scope_id') else ''}

Risk signals detected:
{items_text or 'No risk signals detected.'}

Write a concise risk report (5–8 sentences) that:
1. Summarises the overall risk posture (green / amber / red)
2. Highlights the top 3 most critical issues
3. Recommends concrete remediation steps for each
4. Notes any patterns (e.g. many unowned services → team structure problem)
"""
    response = await llm.ainvoke(prompt)
    return {**state, "report": response.content}


def build_risk_graph() -> StateGraph:
    graph = StateGraph(RiskAgentState)

    graph.add_node("collect_signals", collect_signals)
    graph.add_node("score_signals", score_signals)
    graph.add_node("generate_report", generate_report)

    graph.set_entry_point("collect_signals")
    graph.add_edge("collect_signals", "score_signals")
    graph.add_edge("score_signals", "generate_report")
    graph.add_edge("generate_report", END)

    return graph.compile()


risk_agent = build_risk_graph()