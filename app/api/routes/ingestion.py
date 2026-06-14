"""
Ingestion API – manually trigger ingestion runs and check status.
Also receives webhooks from Slack / GitHub.
"""
import hashlib
import hmac
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis import get_queue
from app.core.security import get_current_principal
from app.schemas import IngestionStatusResponse, IngestionTriggerRequest

logger = get_logger(__name__)
router = APIRouter()

SOURCE_TASK_MAP = {
    "slack": "app.ingestion.queue.tasks.ingest_slack",
    "github": "app.ingestion.queue.tasks.ingest_github",
    "jira": "app.ingestion.queue.tasks.ingest_jira",
    "gdocs": "app.ingestion.queue.tasks.ingest_gdocs",
}


@router.post("/trigger", response_model=IngestionStatusResponse)
async def trigger_ingestion(
    req: IngestionTriggerRequest,
    principal: dict[str, Any] = Depends(get_current_principal),
) -> Any:
    queue = await get_queue()

    sources = list(SOURCE_TASK_MAP.keys()) if req.source == "all" else [req.source]
    job_ids = []

    for source in sources:
        job = await queue.enqueue(
            SOURCE_TASK_MAP[source],
            full_sync=req.full_sync,
            _job_id=f"ingest-{source}-{int(datetime.now(timezone.utc).timestamp())}",
        )
        job_ids.append(str(job))
        logger.info("ingestion.queued", source=source, job_id=str(job))

    return IngestionStatusResponse(
        job_id=",".join(job_ids),
        source=req.source,
        status="queued",
        queued_at=datetime.now(timezone.utc),
    )


# ── Slack webhook ─────────────────────────────────────────────────────────────

@router.post("/webhooks/slack")
async def slack_webhook(
    request: Request,
    x_slack_signature: str = Header(None),
    x_slack_request_timestamp: str = Header(None),
) -> Any:
    body = await request.body()

    # Verify Slack signature
    if settings.slack_signing_secret:
        sig_basestring = f"v0:{x_slack_request_timestamp}:{body.decode()}"
        expected = "v0=" + hmac.new(
            settings.slack_signing_secret.encode(),
            sig_basestring.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, x_slack_signature or ""):
            raise HTTPException(status_code=401, detail="Invalid Slack signature")

    payload = await request.json()

    # Slack URL verification challenge
    if payload.get("type") == "url_verification":
        return {"challenge": payload["challenge"]}

    # Queue real-time processing
    queue = await get_queue()
    await queue.enqueue("app.ingestion.queue.tasks.process_slack_event", event=payload)

    return {"ok": True}


# ── GitHub webhook ────────────────────────────────────────────────────────────

@router.post("/webhooks/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str = Header(None),
    x_github_event: str = Header("push"),
) -> Any:
    body = await request.body()

    if settings.github_token and x_hub_signature_256:
        expected = "sha256=" + hmac.new(
            settings.github_token.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="Invalid GitHub signature")

    payload = await request.json()
    queue = await get_queue()
    await queue.enqueue(
        "app.ingestion.queue.tasks.process_github_event",
        event_type=x_github_event,
        payload=payload,
    )

    return {"ok": True}