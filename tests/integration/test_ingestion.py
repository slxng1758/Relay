"""
Integration tests for BaseConnector's shared upsert helpers.

Requires a reachable Postgres (`docker compose up -d postgres`); skipped via
the `db_session` fixture if the database is unavailable.
"""
from __future__ import annotations

from app.db.models.edges import EdgeType
from app.db.models.nodes import NodeType, SourceSystem, Team
from app.ingestion.base_connector import BaseConnector, IngestionStats


class _TestConnector(BaseConnector):
    source_system = SourceSystem.MANUAL

    async def sync(self, full_sync: bool = False) -> IngestionStats:
        return IngestionStats()


async def test_upsert_node_creates_then_updates(db_session) -> None:
    connector = _TestConnector()

    team, created = await connector.upsert_node(
        db_session, Team, external_id="integration-test-team", name="Test Team"
    )
    assert created is True
    assert team.name == "Test Team"

    team_again, created_again = await connector.upsert_node(
        db_session, Team, external_id="integration-test-team", name="Test Team Renamed"
    )
    assert created_again is False
    assert team_again.id == team.id
    assert team_again.name == "Test Team Renamed"


async def test_upsert_edge_creates_then_dedupes(db_session) -> None:
    connector = _TestConnector()

    team_a, _ = await connector.upsert_node(
        db_session, Team, external_id="integration-test-team-a", name="Team A"
    )
    team_b, _ = await connector.upsert_node(
        db_session, Team, external_id="integration-test-team-b", name="Team B"
    )

    edge, created = await connector.upsert_edge(
        db_session,
        source_id=team_a.id,
        source_type=NodeType.TEAM,
        target_id=team_b.id,
        target_type=NodeType.TEAM,
        edge_type=EdgeType.RELATED_TO,
    )
    assert created is True

    edge_again, created_again = await connector.upsert_edge(
        db_session,
        source_id=team_a.id,
        source_type=NodeType.TEAM,
        target_id=team_b.id,
        target_type=NodeType.TEAM,
        edge_type=EdgeType.RELATED_TO,
    )
    assert created_again is False
    assert edge_again.id == edge.id
