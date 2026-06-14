"""End-to-end smoke test: the API boots and `/health` responds with the expected shape."""
from __future__ import annotations


async def test_health_endpoint(client) -> None:
    response = await client.get("/health")

    assert response.status_code == 200

    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert body["version"]
    assert body["db"] in {"ok", "error"}
    assert body["redis"] in {"ok", "error"}
