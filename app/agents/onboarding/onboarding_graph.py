"""
Onboarding / Handoff Document Agent
─────────────────────────────────────
Given a person + team, gathers all relevant graph context and generates
a structured onboarding or handoff document in Markdown.

Agent-to-agent: for each service the team owns, calls the dependency agent
to include real dependency chain context in the generated document.
Capped at 3 services to bound latency.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.agents.state import OnboardingResult
from app.core.database import db_session
from app.core.llm import complete
from app.core.logging import get_logger
from app.db.models.edges import EdgeType
from app.db.models.nodes import Decision, Person, Service, Task, Team
from app.db.repositories.edge_repository import EdgeRepository

logger = get_logger(__name__)


async def _load_person(person_id: str) -> list[dict[str, Any]]:
    context: list[dict[str, Any]] = []
    async with db_session() as session:
        row = await session.execute(select(Person).where(Person.id == person_id))
        person = row.scalar_one_or_none()
        if not person:
            return context
        context.append({
            "type": "person", "id": str(person.id),
            "name": person.display_name, "email": person.email,
            "github": person.github_login,
        })
        owns = await EdgeRepository(session).get_outgoing(person.id, EdgeType.OWNS)
        context.extend(
            {"type": "ownership", "target_id": str(e.target_id), "target_type": e.target_type}
            for e in owns
        )
    return context


async def _load_team(team_id: str) -> list[dict[str, Any]]:
    context: list[dict[str, Any]] = []
    async with db_session() as session:
        row = await session.execute(select(Team).where(Team.id == team_id))
        team = row.scalar_one_or_none()
        if team:
            context.append({
                "type": "team", "id": str(team.id),
                "name": team.name, "slack_channel": team.slack_channel_id,
            })

        for svc in (await session.execute(select(Service).where(Service.owner_team_id == team_id))).scalars():
            context.append({
                "type": "service", "id": str(svc.id),
                "name": svc.name, "status": svc.status, "repo_url": svc.repo_url,
            })

        for member in (await session.execute(select(Person).where(Person.team_id == team_id))).scalars():
            context.append({
                "type": "team_member", "id": str(member.id),
                "name": member.display_name, "email": member.email,
            })

    return context


async def _gather_open_work(team_id: str) -> list[dict[str, Any]]:
    async with db_session() as session:
        rows = await session.execute(
            select(Task)
            .where(Task.team_id == team_id, Task.status.in_(["open", "in_progress"]))
            .limit(20)
        )
        return [
            {
                "type": "open_task", "id": str(t.id), "title": t.title,
                "status": t.status, "priority": t.priority, "jira_key": t.jira_key,
                "due_date": t.due_date.isoformat() if t.due_date else None,
            }
            for t in rows.scalars()
        ]


async def _gather_decisions() -> list[dict[str, Any]]:
    async with db_session() as session:
        rows = await session.execute(select(Decision).where(Decision.status == "open").limit(10))
        return [
            {
                "type": "open_decision", "id": str(d.id),
                "title": d.title, "summary": d.summary, "source_url": d.source_url,
            }
            for d in rows.scalars()
        ]


async def _enrich_services_with_dependencies(context: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Agent-to-agent call: for each service the team owns, run the dependency
    agent and attach a summary + risk score to the service context entry.
    Capped at 3 services to bound latency.
    """
    from app.agents.dependency.dependency_graph import run_dependency_agent

    services = [c for c in context if c["type"] == "service"][:3]
    for svc in services:
        logger.info("onboarding_agent.consulting_dependency_agent", service=svc["name"])
        try:
            dep_result = await run_dependency_agent(svc["id"])
            svc["dependency_summary"] = dep_result.summary
            svc["dependency_risk_score"] = dep_result.risk_score
            svc["circular_deps"] = dep_result.circular_deps
        except Exception as exc:
            logger.warning("onboarding_agent.dependency_lookup_failed", service=svc["id"], error=str(exc))

    return context


async def _draft(doc_type: str, context: list[dict[str, Any]]) -> str:
    team_info = [c for c in context if c["type"] == "team"]
    members = [c for c in context if c["type"] == "team_member"]
    services = [c for c in context if c["type"] == "service"]
    open_tasks = [c for c in context if c["type"] == "open_task"]
    decisions = [c for c in context if c["type"] == "open_decision"]
    person_info = [c for c in context if c["type"] == "person"]

    if doc_type == "onboarding":
        instruction = """Generate a comprehensive onboarding document for a new team member. Include:
## Welcome to the Team
## Team Overview (members, mission, Slack channel)
## Services We Own (with repo links, status, dependency summary, and risk score)
## Your First Week (what to read, who to meet, what to set up)
## Open Work (current priorities and in-flight tasks)
## Open Decisions (decisions the team is currently working through)
## Key Contacts"""
    else:
        instruction = """Generate a handoff document for someone leaving the team. Include:
## Handoff Overview
## Services Owned (status, dependency chains, known risks, runbook links)
## In-Flight Work (tasks, owners, next steps)
## Open Decisions (context, options considered, recommended path)
## Key Relationships (stakeholders, dependencies on other teams)
## Things That Will Surprise You (institutional knowledge, gotchas)"""

    prompt = f"""{instruction}

Context data:
Team: {team_info}
Members: {members}
Services (with dependency context): {services}
Open tasks: {open_tasks}
Open decisions: {decisions}
Person: {person_info}

Write the full document in clean Markdown. Be specific — use real names, task titles, service names, and dependency details from the context.
"""
    return await complete(prompt, temperature=0.3)


async def _refine(doc_type: str, draft: str) -> str:
    prompt = f"""Review and lightly edit this {doc_type} document.
Fix any formatting issues, ensure all section headers are present and consistent,
and make sure the tone is clear and direct. Return only the final Markdown document.

{draft}"""
    return await complete(prompt, temperature=0.1)


async def run_onboarding_agent(
    person_id: str,
    team_id: str,
    doc_type: str = "onboarding",
) -> OnboardingResult:
    logger.info("onboarding_agent.start", person_id=person_id, team_id=team_id, doc_type=doc_type)

    context: list[dict[str, Any]] = []
    context.extend(await _load_person(person_id))
    context.extend(await _load_team(team_id))
    context = await _enrich_services_with_dependencies(context)
    context.extend(await _gather_open_work(team_id))
    context.extend(await _gather_decisions())

    draft = await _draft(doc_type, context)
    final = await _refine(doc_type, draft)

    logger.info("onboarding_agent.done", doc_type=doc_type)
    return OnboardingResult(final_document=final)
