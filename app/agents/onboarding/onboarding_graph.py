"""
Onboarding / Handoff Document Agent
─────────────────────────────────────
Given a person + team, gathers all relevant graph context and generates
a structured onboarding or handoff document in Markdown.

Graph flow:
  load_person_context → load_team_context → gather_open_work →
  gather_decisions → draft_document → refine → END
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph
from sqlalchemy import select

from app.agents.state import OnboardingAgentState
from app.core.database import db_session
from app.core.llm import get_llm
from app.core.logging import get_logger
from app.db.models.nodes import Person, Team, Task, Decision, Service
from app.db.models.edges import EdgeType
from app.db.repositories.edge_repository import EdgeRepository

logger = get_logger(__name__)


async def load_person_context(state: OnboardingAgentState) -> OnboardingAgentState:
    """Load the person node and their direct edges."""
    person_id = state["person_id"]
    context: list[dict[str, Any]] = []

    async with db_session() as session:
        result = await session.execute(select(Person).where(Person.id == person_id))
        person = result.scalar_one_or_none()

        if person:
            context.append({
                "type": "person",
                "id": str(person.id),
                "name": person.display_name,
                "email": person.email,
                "github": person.github_login,
            })

            # What does this person own?
            edge_repo = EdgeRepository(session)
            owns = await edge_repo.get_outgoing(person.id, EdgeType.OWNS)
            context.extend([
                {"type": "ownership", "target_id": str(e.target_id), "target_type": e.target_type}
                for e in owns
            ])

    return {**state, "context_nodes": context}


async def load_team_context(state: OnboardingAgentState) -> OnboardingAgentState:
    """Load team services, members, and active repos."""
    team_id = state["team_id"]
    context = state.get("context_nodes", [])

    async with db_session() as session:
        result = await session.execute(select(Team).where(Team.id == team_id))
        team = result.scalar_one_or_none()

        if team:
            context.append({
                "type": "team",
                "id": str(team.id),
                "name": team.name,
                "slack_channel": team.slack_channel_id,
            })

        # Services owned by team
        result = await session.execute(
            select(Service).where(Service.owner_team_id == team_id)
        )
        for svc in result.scalars():
            context.append({
                "type": "service",
                "id": str(svc.id),
                "name": svc.name,
                "status": svc.status,
                "repo_url": svc.repo_url,
            })

        # Members
        result = await session.execute(
            select(Person).where(Person.team_id == team_id)
        )
        for member in result.scalars():
            context.append({
                "type": "team_member",
                "id": str(member.id),
                "name": member.display_name,
                "email": member.email,
            })

    return {**state, "context_nodes": context}


async def gather_open_work(state: OnboardingAgentState) -> OnboardingAgentState:
    """Load open/in-progress tasks assigned to this team."""
    team_id = state["team_id"]
    context = state.get("context_nodes", [])

    async with db_session() as session:
        result = await session.execute(
            select(Task).where(
                Task.team_id == team_id,
                Task.status.in_(["open", "in_progress"]),
            ).limit(20)
        )
        for task in result.scalars():
            context.append({
                "type": "open_task",
                "id": str(task.id),
                "title": task.title,
                "status": task.status,
                "priority": task.priority,
                "jira_key": task.jira_key,
                "due_date": task.due_date.isoformat() if task.due_date else None,
            })

    return {**state, "context_nodes": context}


async def gather_decisions(state: OnboardingAgentState) -> OnboardingAgentState:
    """Load recent open decisions relevant to this team's services."""
    context = state.get("context_nodes", [])
    service_ids = [c["id"] for c in context if c["type"] == "service"]

    if not service_ids:
        return state

    async with db_session() as session:
        result = await session.execute(
            select(Decision).where(Decision.status == "open").limit(10)
        )
        for dec in result.scalars():
            context.append({
                "type": "open_decision",
                "id": str(dec.id),
                "title": dec.title,
                "summary": dec.summary,
                "source_url": dec.source_url,
            })

    return {**state, "context_nodes": context}


async def draft_document(state: OnboardingAgentState) -> OnboardingAgentState:
    """Generate the full document draft using the LLM."""
    llm = get_llm(temperature=0.3)
    doc_type = state.get("doc_type", "onboarding")
    context = state.get("context_nodes", [])

    # Bucket context by type for the prompt
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
## Services We Own (with repo links and status)
## Your First Week (what to read, who to meet, what to set up)
## Open Work (current priorities and in-flight tasks)
## Open Decisions (decisions the team is currently working through)
## Key Contacts"""
    else:
        instruction = """Generate a handoff document for someone leaving the team. Include:
## Handoff Overview
## Services Owned (status, known issues, runbook links)
## In-Flight Work (tasks, owners, next steps)
## Open Decisions (context, options considered, recommended path)
## Key Relationships (stakeholders, dependencies on other teams)
## Things That Will Surprise You (institutional knowledge, gotchas)"""

    prompt = f"""{instruction}

Context data:
Team: {team_info}
Members: {members}
Services: {services}
Open tasks: {open_tasks}
Open decisions: {decisions}
Person: {person_info}

Write the full document in clean Markdown. Be specific — use real names, task titles, and service names from the context.
"""
    response = await llm.ainvoke(prompt)
    return {**state, "draft": response.content}


async def refine_document(state: OnboardingAgentState) -> OnboardingAgentState:
    """Light editing pass: fix formatting, ensure all sections are present."""
    llm = get_llm(temperature=0.1)
    draft = state.get("draft", "")

    prompt = f"""Review and lightly edit this {state.get('doc_type', 'onboarding')} document.
Fix any formatting issues, ensure all section headers are present and consistent,
and make sure the tone is clear and direct. Return only the final Markdown document.

{draft}"""

    response = await llm.ainvoke(prompt)
    return {**state, "final_document": response.content}


def build_onboarding_graph() -> StateGraph:
    graph = StateGraph(OnboardingAgentState)

    graph.add_node("load_person_context", load_person_context)
    graph.add_node("load_team_context", load_team_context)
    graph.add_node("gather_open_work", gather_open_work)
    graph.add_node("gather_decisions", gather_decisions)
    graph.add_node("draft_document", draft_document)
    graph.add_node("refine_document", refine_document)

    graph.set_entry_point("load_person_context")
    graph.add_edge("load_person_context", "load_team_context")
    graph.add_edge("load_team_context", "gather_open_work")
    graph.add_edge("gather_open_work", "gather_decisions")
    graph.add_edge("gather_decisions", "draft_document")
    graph.add_edge("draft_document", "refine_document")
    graph.add_edge("refine_document", END)

    return graph.compile()


onboarding_agent = build_onboarding_graph()