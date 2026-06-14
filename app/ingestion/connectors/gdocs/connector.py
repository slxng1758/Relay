"""
Google Docs connector.

Lists Google Docs in the shared drive configured via
`settings.google_drive_shared_drive_id` and upserts them as `Document` nodes
(content hash from Drive's `md5Checksum`, doc type inferred from the title).
Authenticates with a service account; google-api-python-client is synchronous,
so all calls run in a thread.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build

from app.core.config import settings
from app.core.database import db_session
from app.core.logging import get_logger
from app.db.models.nodes import Document, NodeType, SourceSystem
from app.ingestion.base_connector import BaseConnector, IngestionStats
from app.ingestion.processors.embedding_processor import embed_node

logger = get_logger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Title prefix -> Document.doc_type
_DOC_TYPE_PREFIXES = {
    "RFC": "rfc",
    "ADR": "adr",
    "RUNBOOK": "runbook",
    "SPEC": "spec",
}


class GDocsConnector(BaseConnector):
    source_system = SourceSystem.GDOCS

    def __init__(self) -> None:
        info = json.loads(settings.google_service_account_json)
        credentials = service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)
        self._client = build("drive", "v3", credentials=credentials)

    async def sync(self, full_sync: bool = False) -> IngestionStats:
        stats = IngestionStats()
        files = await asyncio.to_thread(self._list_files)

        async with db_session() as session:
            for file in files:
                doc, created = await self.upsert_node(
                    session,
                    Document,
                    external_id=file["id"],
                    title=file["name"],
                    content_hash=file.get("md5Checksum"),
                    doc_url=file.get("webViewLink"),
                    doc_type=self._infer_doc_type(file["name"]),
                )
                stats.nodes_created += int(created)
                stats.nodes_updated += int(not created)

                await embed_node(session, doc.id, NodeType.DOCUMENT, file["name"])

        logger.info("gdocs.sync.complete", **stats.__dict__)
        return stats

    def _list_files(self) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        page_token: str | None = None

        while True:
            response = (
                self._client.files()
                .list(
                    q="mimeType='application/vnd.google-apps.document' and trashed=false",
                    corpora="drive",
                    driveId=settings.google_drive_shared_drive_id,
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                    fields="nextPageToken, files(id, name, webViewLink, md5Checksum)",
                    pageToken=page_token,
                    pageSize=100,
                )
                .execute()
            )
            files.extend(response.get("files", []))

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return files

    @staticmethod
    def _infer_doc_type(title: str) -> str:
        upper = title.upper()
        for prefix, doc_type in _DOC_TYPE_PREFIXES.items():
            if upper.startswith(prefix):
                return doc_type
        return "doc"
