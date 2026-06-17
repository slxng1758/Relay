"""
Coordinator Agent
─────────────────
The only true agent in the system: receives a natural-language question,
uses Anthropic tool-calling to decide which specialist(s) to invoke,
executes them, and synthesises a single coherent answer.

Specialists are called as tools. The coordinator loop runs until the LLM
produces a final text response (stop_reason == "end_turn") or the iteration
cap is hit.

Agent-to-agent calls (risk→decision, onboarding→dependency) happen inside
the specialist functions, not here — the coordinator only sees their results.
"""
from __future__ import annotations

import json
from typing import Any

import anthropic

from app.core.llm import get_async_anthropic
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = """You are an operational intelligence coordinator for an engineering organisation.
You have access to a live knowledge graph of the org's teams, services, decisions, and work.

You have four specialist tools:
- analyze_dependencies: maps a service's dependency chain, detects cycles, scores blast-radius risk
- query_decisions: retrieves and reconstructs past architectural/engineering decisions
- assess_risk: scans for risk signals (unowned services, overdue work, bus factor, stale decisions)
- generate_onboarding_doc: generates a tailored onboarding or handoff document for a person joining/leaving a team

Rules:
- Use the minimum number of tools needed to answer the question fully.
- If a question spans multiple domains (e.g. "what's risky about auth-service and why was it built that way?"), call both relevant tools.
- Synthesise tool results into a single, direct answer. Do not repeat raw tool output verbatim.
- If you cannot answer without information the user hasn't provided (e.g. a service ID), ask for it.
"""

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "analyze_dependencies",
        "description": (
            "Analyse a service's full dependency chain, detect circular dependencies, "
            "and produce a blast-radius risk score. Use when asked what a service depends on, "
            "what would break if a service went down, or whether dependencies are healthy."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "service_id": {"type": "string", "description": "UUID of the service to analyse"},
            },
            "required": ["service_id"],
        },
    },
    {
        "name": "query_decisions",
        "description": (
            "Retrieve and reconstruct the history behind architectural and engineering decisions. "
            "Use when asked why something was built a certain way, what decisions were made about "
            "a topic, or the reasoning behind a technical choice."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language question about decisions"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "assess_risk",
        "description": (
            "Scan the operational graph for risk signals: unowned services, overdue tasks, "
            "bus-factor problems, stale open decisions. Use when asked about risk, what might break, "
            "what needs attention, or overall team/org health."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["team", "service", "global"],
                    "description": "Scope of the assessment",
                },
                "scope_id": {
                    "type": "string",
                    "description": "UUID of the team or service (omit for global scope)",
                },
            },
            "required": ["scope"],
        },
    },
    {
        "name": "generate_onboarding_doc",
        "description": (
            "Generate a tailored onboarding or handoff document for a person joining or leaving a team. "
            "Use when asked to onboard someone, create a handoff doc, or get someone up to speed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "person_id": {"type": "string", "description": "UUID of the person"},
                "team_id": {"type": "string", "description": "UUID of the team"},
                "doc_type": {
                    "type": "string",
                    "enum": ["onboarding", "handoff"],
                    "description": "Type of document to generate",
                },
            },
            "required": ["person_id", "team_id", "doc_type"],
        },
    },
]


async def _dispatch(name: str, inputs: dict[str, Any]) -> dict[str, Any]:
    """Execute the named specialist and return a JSON-serialisable result."""
    if name == "analyze_dependencies":
        from app.agents.dependency.dependency_graph import run_dependency_agent
        result = await run_dependency_agent(service_id=inputs["service_id"])
        return {
            "dependency_chain": result.dependency_chain,
            "circular_deps": result.circular_deps,
            "risk_score": result.risk_score,
            "summary": result.summary,
        }

    if name == "query_decisions":
        from app.agents.decision.decision_graph import run_decision_agent
        result = await run_decision_agent(query=inputs["query"])
        return {
            "answer": result.answer,
            "decision_timeline": result.decision_timeline,
        }

    if name == "assess_risk":
        from app.agents.risk.risk_graph import run_risk_agent
        result = await run_risk_agent(
            scope=inputs["scope"],
            scope_id=inputs.get("scope_id"),
        )
        return {"risk_items": result.risk_items, "report": result.report}

    if name == "generate_onboarding_doc":
        from app.agents.onboarding.onboarding_graph import run_onboarding_agent
        result = await run_onboarding_agent(
            person_id=inputs["person_id"],
            team_id=inputs["team_id"],
            doc_type=inputs.get("doc_type", "onboarding"),
        )
        return {"document": result.final_document}

    raise ValueError(f"Unknown tool: {name}")


async def run_coordinator(question: str, run_id: str) -> str:
    """
    Main coordinator loop.
    Runs up to 5 iterations to prevent runaway tool chains.
    """
    client = get_async_anthropic()
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    logger.info("coordinator.start", run_id=run_id)

    for iteration in range(5):
        response = await client.messages.create(
            model=settings.default_model,
            max_tokens=settings.agent_max_tokens,
            system=_SYSTEM_PROMPT,
            messages=messages,
            tools=_TOOLS,  # type: ignore[arg-type]
        )

        logger.info(
            "coordinator.llm_response",
            run_id=run_id,
            iteration=iteration,
            stop_reason=response.stop_reason,
        )

        if response.stop_reason == "end_turn":
            text = next(
                (b.text for b in response.content if hasattr(b, "text")),
                "",
            )
            logger.info("coordinator.done", run_id=run_id, iterations=iteration + 1)
            return text

        if response.stop_reason != "tool_use":
            break

        # Execute all tool calls in this turn
        tool_results: list[dict[str, Any]] = []
        for block in response.content:
            if not isinstance(block, anthropic.types.ToolUseBlock):
                continue
            logger.info("coordinator.tool_call", run_id=run_id, tool=block.name, inputs=block.input)
            try:
                result = await _dispatch(block.name, block.input)  # type: ignore[arg-type]
            except Exception as exc:
                logger.error("coordinator.tool_error", run_id=run_id, tool=block.name, error=str(exc))
                result = {"error": str(exc)}

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, default=str),
            })

        messages.append({"role": "assistant", "content": response.content})  # type: ignore[arg-type]
        messages.append({"role": "user", "content": tool_results})

    logger.warning("coordinator.iteration_cap_reached", run_id=run_id)
    return "Could not produce a complete answer within the allowed number of steps."
