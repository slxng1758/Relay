"""
Agents API – trigger specialist agents or ask the coordinator directly.
All endpoints require a JWT bearer token.
"""
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from app.core.logging import get_logger
from app.schemas import (
    DecisionQueryRequest, DecisionQueryResponse,
    DependencyRequest, DependencyResponse,
    OnboardingRequest, OnboardingResponse,
    RiskRequest, RiskResponse,
)
from app.schemas.agents import CoordinatorRequest, CoordinatorResponse

logger = get_logger(__name__)
router = APIRouter()


# ── Coordinator (natural-language entry point) ────────────────────────────────

@router.post("/query", response_model=CoordinatorResponse)
async def query(req: CoordinatorRequest) -> Any:
    from app.agents.coordinator import run_coordinator

    run_id = str(uuid.uuid4())
    logger.info("coordinator.request", run_id=run_id)
    try:
        answer = await run_coordinator(question=req.question, run_id=run_id)
    except Exception as exc:
        logger.error("coordinator.error", run_id=run_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return CoordinatorResponse(answer=answer, run_id=run_id)


# ── Direct specialist endpoints (programmatic / deterministic access) ─────────

@router.post("/dependency", response_model=DependencyResponse)
async def run_dependency_agent(req: DependencyRequest) -> Any:
    from app.agents.dependency.dependency_graph import run_dependency_agent as _run

    run_id = str(uuid.uuid4())
    logger.info("agent.dependency.start", run_id=run_id, service_id=str(req.service_id))
    try:
        result = await _run(service_id=str(req.service_id))
    except Exception as exc:
        logger.error("agent.dependency.error", run_id=run_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return DependencyResponse(
        service_id=req.service_id,
        dependency_chain=result.dependency_chain,
        circular_deps=result.circular_deps,
        risk_score=result.risk_score,
        summary=result.summary,
        run_id=run_id,
    )


@router.post("/decisions/query", response_model=DecisionQueryResponse)
async def run_decision_agent(req: DecisionQueryRequest) -> Any:
    from app.agents.decision.decision_graph import run_decision_agent as _run

    run_id = str(uuid.uuid4())
    logger.info("agent.decision.start", run_id=run_id)
    try:
        result = await _run(query=req.query)
    except Exception as exc:
        logger.error("agent.decision.error", run_id=run_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return DecisionQueryResponse(
        query=req.query,
        answer=result.answer,
        decision_timeline=result.decision_timeline,
        run_id=run_id,
    )


@router.post("/risk", response_model=RiskResponse)
async def run_risk_agent(req: RiskRequest) -> Any:
    from app.agents.risk.risk_graph import run_risk_agent as _run

    run_id = str(uuid.uuid4())
    logger.info("agent.risk.start", run_id=run_id, scope=req.scope)
    try:
        result = await _run(scope=req.scope, scope_id=str(req.scope_id) if req.scope_id else None)
    except Exception as exc:
        logger.error("agent.risk.error", run_id=run_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return RiskResponse(
        scope=req.scope,
        risk_items=result.risk_items,
        report=result.report,
        run_id=run_id,
    )


@router.post("/onboarding", response_model=OnboardingResponse)
async def run_onboarding_agent(req: OnboardingRequest) -> Any:
    from app.agents.onboarding.onboarding_graph import run_onboarding_agent as _run

    run_id = str(uuid.uuid4())
    logger.info("agent.onboarding.start", run_id=run_id, person_id=str(req.person_id))
    try:
        result = await _run(
            person_id=str(req.person_id),
            team_id=str(req.team_id),
            doc_type=req.doc_type,
        )
    except Exception as exc:
        logger.error("agent.onboarding.error", run_id=run_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return OnboardingResponse(
        person_id=req.person_id,
        team_id=req.team_id,
        doc_type=req.doc_type,
        document=result.final_document,
        run_id=run_id,
    )
