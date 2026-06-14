"""
Agents API – trigger LangGraph agent runs via HTTP.
Each endpoint is async and streams or returns the full result.
"""
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas import (
    DependencyRequest, DependencyResponse,
    DecisionQueryRequest, DecisionQueryResponse,
    RiskRequest, RiskResponse,
    OnboardingRequest, OnboardingResponse,
)
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


# ── Dependency agent ──────────────────────────────────────────────────────────

@router.post("/dependency", response_model=DependencyResponse)
async def run_dependency_agent(req: DependencyRequest) -> Any:
    from app.agents.dependency.dependency_graph import dependency_agent

    run_id = str(uuid.uuid4())
    logger.info("agent.dependency.start", run_id=run_id, service_id=str(req.service_id))

    try:
        result = await dependency_agent.ainvoke(
            {
                "run_id": run_id,
                "target_service_id": str(req.service_id),
                "messages": [],
            }
        )
    except Exception as exc:
        logger.error("agent.dependency.error", run_id=run_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return DependencyResponse(
        service_id=req.service_id,
        dependency_chain=result.get("dependency_chain", []),
        circular_deps=result.get("circular_deps", []),
        risk_score=result.get("risk_score", 0.0),
        summary=result.get("summary", ""),
        run_id=run_id,
    )


# ── Decision agent ────────────────────────────────────────────────────────────

@router.post("/decisions/query", response_model=DecisionQueryResponse)
async def run_decision_agent(req: DecisionQueryRequest) -> Any:
    from app.agents.decision.decision_graph import decision_agent

    run_id = str(uuid.uuid4())
    logger.info("agent.decision.start", run_id=run_id)

    try:
        result = await decision_agent.ainvoke(
            {"run_id": run_id, "query": req.query, "messages": []}
        )
    except Exception as exc:
        logger.error("agent.decision.error", run_id=run_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return DecisionQueryResponse(
        query=req.query,
        answer=result.get("answer", ""),
        decision_timeline=result.get("decision_timeline", []),
        run_id=run_id,
    )


# ── Risk agent ────────────────────────────────────────────────────────────────

@router.post("/risk", response_model=RiskResponse)
async def run_risk_agent(req: RiskRequest) -> Any:
    from app.agents.risk.risk_graph import risk_agent

    run_id = str(uuid.uuid4())
    logger.info("agent.risk.start", run_id=run_id, scope=req.scope)

    try:
        result = await risk_agent.ainvoke(
            {
                "run_id": run_id,
                "scope": req.scope,
                "scope_id": str(req.scope_id) if req.scope_id else None,
                "messages": [],
            }
        )
    except Exception as exc:
        logger.error("agent.risk.error", run_id=run_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return RiskResponse(
        scope=req.scope,
        risk_items=result.get("risk_items", []),
        report=result.get("report", ""),
        run_id=run_id,
    )


# ── Onboarding agent ──────────────────────────────────────────────────────────

@router.post("/onboarding", response_model=OnboardingResponse)
async def run_onboarding_agent(req: OnboardingRequest) -> Any:
    from app.agents.onboarding.onboarding_graph import onboarding_agent

    run_id = str(uuid.uuid4())
    logger.info(
        "agent.onboarding.start", run_id=run_id,
        person_id=str(req.person_id), doc_type=req.doc_type,
    )

    try:
        result = await onboarding_agent.ainvoke(
            {
                "run_id": run_id,
                "person_id": str(req.person_id),
                "team_id": str(req.team_id),
                "doc_type": req.doc_type,
                "messages": [],
            }
        )
    except Exception as exc:
        logger.error("agent.onboarding.error", run_id=run_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return OnboardingResponse(
        person_id=req.person_id,
        team_id=req.team_id,
        doc_type=req.doc_type,
        document=result.get("final_document", ""),
        run_id=run_id,
    )