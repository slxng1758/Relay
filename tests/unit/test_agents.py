"""
Unit tests for pure logic helpers in each agent module.

All helpers under test are synchronous and require no DB, Redis, or LLM calls,
so these run without any external services.
"""
from __future__ import annotations

from app.agents.decision.decision_graph import _build_timeline
from app.agents.dependency.dependency_graph import _detect_cycles, _score_risk
from app.agents.risk.risk_graph import _score
from app.db.models.edges import EdgeType


# ── dependency_graph ─────────────────────────────────────────────────────────

def test_detect_cycles_finds_circular_dependency() -> None:
    chain = [
        {"source_id": "a", "target_id": "b", "depth": 1},
        {"source_id": "b", "target_id": "c", "depth": 2},
        {"source_id": "c", "target_id": "a", "depth": 3},
    ]

    cycles = _detect_cycles(chain)

    assert cycles
    assert any({"a", "b", "c"} <= set(cycle) for cycle in cycles)


def test_detect_cycles_no_cycle() -> None:
    chain = [
        {"source_id": "a", "target_id": "b", "depth": 1},
        {"source_id": "b", "target_id": "c", "depth": 2},
    ]

    assert _detect_cycles(chain) == []


def test_score_risk_combines_depth_cycles_and_fan_in() -> None:
    chain = [
        {"source_id": "a", "target_id": "b"},
        {"source_id": "a", "target_id": "c"},
    ]
    cycles = [["a", "b", "a"]]

    score = _score_risk(chain, cycles)

    # depth_score = 2/20 = 0.1, cycle_penalty = min(1*0.25, 1) = 0.25, fan_in = 2/2 = 1.0
    expected = round(0.1 * 0.4 + 0.25 * 0.4 + 1.0 * 0.2, 3)
    assert score == expected


def test_score_risk_zero_for_empty_chain() -> None:
    assert _score_risk([], []) == 0.0


# ── risk_graph ───────────────────────────────────────────────────────────────

def test_score_dedupes_and_sorts_by_severity() -> None:
    overdue = {
        "type": "overdue_task", "severity": "medium",
        "entity_id": "t1", "entity_name": "Task 1", "detail": "...",
    }
    unowned = {
        "type": "unowned_service", "severity": "high",
        "entity_id": "s1", "entity_name": "Service 1", "detail": "...",
    }

    result = _score([overdue, unowned, dict(overdue)])  # duplicate of overdue

    assert len(result) == 2
    assert result[0]["type"] == "unowned_service"   # high sorts first
    assert result[0]["score"] == 3
    assert result[1]["score"] == 2


def test_score_empty_signals() -> None:
    assert _score([]) == []


# ── decision_graph ───────────────────────────────────────────────────────────

def test_build_timeline_sorts_and_marks_supersession() -> None:
    enriched = [
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

    timeline = _build_timeline(enriched)

    assert [d["id"] for d in timeline] == ["older", "newer"]
    assert timeline[0]["superseded_by"] == ["newer"]
    assert timeline[1]["superseded_by"] == []


def test_build_timeline_no_supersession() -> None:
    enriched = [
        {"id": "d1", "title": "Decision 1", "decided_at": "2024-01-01", "incoming_edges": []},
        {"id": "d2", "title": "Decision 2", "decided_at": "2024-03-01", "incoming_edges": []},
    ]

    timeline = _build_timeline(enriched)

    assert [d["id"] for d in timeline] == ["d1", "d2"]
    assert all(d["superseded_by"] == [] for d in timeline)
