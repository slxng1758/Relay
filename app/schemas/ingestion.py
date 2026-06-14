"""Request/response schemas for app/api/routes/ingestion.py."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class IngestionTriggerRequest(BaseModel):
    source: Literal["slack", "github", "jira", "gdocs", "all"] = "all"
    full_sync: bool = False


class IngestionStatusResponse(BaseModel):
    job_id: str
    source: str
    status: str
    queued_at: datetime
