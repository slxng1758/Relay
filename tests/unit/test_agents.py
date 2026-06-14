"""
Unit tests for the pure-logic node functions in each agent graph.

These operate on plain state dicts with no DB, Redis, or LLM calls, so they
run without any external services.
"""
from __future__ import annotations

from app.agents.decision.decision_graph import build_timeline
from app.agents.dependency.dependency_graph import detect_cycles, score_risk
from app.agents.risk.risk_graph import score_signals
from app.db.models.edges import EdgeType


# ── dependency_graph ─────────────────────────────────────────────────────────

async def test_detect_cycles_finds_circular_dependency() -> None:
    state = {
        "dependency_chain": [
            {"source_id": "a", "target_id": "b", "depth": 1},
            {"source_id": "b", "target_id": "c", "depth": 2},
            {"source_id": "c", "target_id": "a", "depth": 3},
        ]
    }

    result = await detect_cycles(state)

    assert result["circular_deps"]
    assert any({"a", "b", "c"} <= set(cycle) for cycle in result["circular_deps"])


async def test_detect_cycles_no_cycle() -> None:
    state = {
        "dependency_chain": [
            {"source_id": "a", "target_id": "b", "depth": 1},
            {"source_id": "b", "target_id": "c", "depth": 2},
        ]
    }

    result = await detect_cycles(state)

    assert result["circular_deps"] == []


async def test_score_risk_combines_depth_cycles_and_fan_in() -> None:
    state = {
        "dependency_chain": [
            {"source_id": "a", "target_id": "b"},
            {"source_id": "a", "target_id": "c"},
        ],
        "circular_deps": [["a", "b", "a"]],
    }

    result = await score_risk(state)

    # depth_score = 2/20 = 0.1, cycle_penalty = min(1*0.25, 1) = 0.25, fan_in = 2/2 = 1.0
    expected = round(0.1 * 0.4 + 0.25 * 0.4 + 1.0 * 0.2, 3)
    assert result["risk_score"] == expected


# ── risk_graph ───────────────────────────────────────────────────────────────

async def test_score_signals_dedupes_and_sorts_by_severity() -> None:
    overdue = {
        "type": "overdue_task",
        "severity": "medium",
        "entity_id": "t1",
        "entity_name": "Task 1",
        "detail": "...",
    }
    unowned = {
        "type": "unowned_service",
        "severity": "high",
        "entity_id": "s1",
        "entity_name": "Service 1",
        "detail": "...",
    }
    state = {"signals": [overdue, unowned, dict(overdue)]}  # last entry is a duplicate

    result = await score_signals(state)

    assert len(result["risk_items"]) == 2
    assert result["risk_items"][0]["type"] == "unowned_service"  # high severity sorts first
    assert result["risk_items"][0]["score"] == 3
    assert result["risk_items"][1]["score"] == 2


# ── decision_graph ───────────────────────────────────────────────────────────

async def test_build_timeline_sorts_and_marks_supersession() -> None:
    state = {
        "reconstructed_context": [
            {
                "id": "newer",
                "title": "Use service B",
                "decided_at": "2024-02-01T00:00:00+00:00",
                "incoming_edges": [],
            },
            {
                "id": "older",
                "title": "Use service A",
                "decided_at": "2024-01-01T00:00:00+00:00",
                "incoming_edges": [
                    {"type": EdgeType.SUPERSEDES, "source_id": "newer", "source_type": "decision"}
                ],
            },
        ]
    }

    result = await build_timeline(state)
    timeline = result["decision_timeline"]

    assert [d["id"] for d in timeline] == ["older", "newer"]
    assert timeline[0]["superseded_by"] == ["newer"]
    assert timeline[1]["superseded_by"] == []
