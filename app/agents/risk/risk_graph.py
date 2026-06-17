"""
Risk Detection Agent
────────────────────
Scans the operational graph for risk signals:
  - Unowned services / repos
  - Stale open tasks past due date
  - Single-person ownership (bus factor = 1)
  - Open decisions with no resolution > 30 days

Agent-to-agent: for unowned-service and bus-factor signals, consults the
decision agent to check whether the risk is explained by a past decision
(e.g. an intentional deprecation). This prevents false positives and produces
more accurate severity scores.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from app.agents.state import RiskResult
from app.core.database import db_session
from app.core.llm import complete
from app.core.logging import get_logger
from app.db.models.edges import Edge, EdgeType
from app.db.models.nodes import Decision, Service, Task

logger = get_logger(__name__)

STALE_TASK_DAYS = 14
STALE_DECISION_DAYS = 30

# Signal types that may have a known historical explanation
_DECISION_CHECKABLE = {"unowned_service", "bus_factor"}


async def _collect_signals() -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)

    async with db_session() as session:
        for svc in (await session.execute(select(Service).where(Service.owner_team_id.is_(None)))).scalars():
            signals.append({
                "type": "unowned_service", "severity": "high",
                "entity_id": str(svc.id), "entity_name": svc.name,
                "detail": f"Service '{svc.name}' has no owning team",
            })

        for task in (await session.execute(
            select(Task).where(
                Task.status.in_(["open", "in_progress"]),
                Task.due_date < now - timedelta(days=STALE_TASK_DAYS),
            )
        )).scalars():
            signals.append({
                "type": "overdue_task", "severity": "medium",
                "entity_id": str(task.id), "entity_name": task.title,
                "detail": f"Task '{task.title}' overdue (due {task.due_date})",
            })

        for dec in (await session.execute(
            select(Decision).where(
                Decision.status == "open",
                Decision.created_at < now - timedelta(days=STALE_DECISION_DAYS),
            )
        )).scalars():
            signals.append({
                "type": "stale_decision", "severity": "medium",
                "entity_id": str(dec.id), "entity_name": dec.title,
                "detail": f"Decision '{dec.title}' unresolved for > {STALE_DECISION_DAYS} days",
            })

        for row in (await session.execute(
            select(Edge.source_id, func.count(Edge.target_id).label("owned"))
            .where(Edge.edge_type == EdgeType.OWNS, Edge.source_type == "person")
            .group_by(Edge.source_id)
            .having(func.count(Edge.target_id) > 2)
        )):
            signals.append({
                "type": "bus_factor", "severity": "high",
                "entity_id": str(row.source_id), "entity_name": str(row.source_id),
                "detail": f"Person owns {row.owned} services solo – single point of failure",
            })

    return signals


def _score(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    severity_map = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for sig in signals:
        key = f"{sig['type']}:{sig['entity_id']}"
        if key in seen:
            continue
        seen.add(key)
        items.append({**sig, "score": severity_map.get(sig["severity"], 1)})
    return sorted(items, key=lambda r: r["score"], reverse=True)


async def _enrich_with_decision_context(risk_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Agent-to-agent call: for signals that may have historical explanations,
    ask the decision agent whether a past decision accounts for the risk.
    Caps at 3 lookups to bound latency.
    """
    from app.agents.decision.decision_graph import run_decision_agent

    checkable = [r for r in risk_items if r["type"] in _DECISION_CHECKABLE][:3]
    if not checkable:
        return risk_items

    for item in checkable:
        query = (
            f"Was there a decision to intentionally leave '{item['entity_name']}' "
            f"unowned, deprecate it, or accept this risk ({item['type']})?"
        )
        logger.info("risk_agent.consulting_decision_agent", signal=item["type"], entity=item["entity_name"])
        result = await run_decision_agent(query)

        if result.decision_timeline:
            item["decision_context"] = result.answer
            # Downgrade severity if a decision explicitly accounts for this
            if item["severity"] == "high" and result.decision_timeline:
                item["severity"] = "medium"
                item["score"] = 2
                item["detail"] += " (see decision context)"

    return sorted(risk_items, key=lambda r: r["score"], reverse=True)


async def _generate_report(scope: str, scope_id: str | None, risk_items: list[dict[str, Any]]) -> str:
    items_text = "\n".join(
        f"- [{r['severity'].upper()}] {r['type']}: {r['detail']}"
        + (f"\n  Decision context: {r['decision_context']}" if r.get("decision_context") else "")
        for r in risk_items[:20]
    )
    prompt = f"""You are an engineering risk analyst reviewing an operational graph.

Scope: {scope}{(' / ' + scope_id) if scope_id else ''}

Risk signals detected:
{items_text or 'No risk signals detected.'}

Write a concise risk report (5–8 sentences) that:
1. Summarises the overall risk posture (green / amber / red)
2. Highlights the top 3 most critical issues
3. Recommends concrete remediation steps for each
4. Notes any risks that are explained by past decisions and can be deprioritised
"""
    return await complete(prompt, temperature=0.1)


async def run_risk_agent(scope: str, scope_id: str | None = None) -> RiskResult:
    logger.info("risk_agent.start", scope=scope, scope_id=scope_id)
    signals = await _collect_signals()
    risk_items = _score(signals)
    risk_items = await _enrich_with_decision_context(risk_items)
    report = await _generate_report(scope, scope_id, risk_items)
    logger.info("risk_agent.done", risk_items=len(risk_items))
    return RiskResult(risk_items=risk_items, report=report)
