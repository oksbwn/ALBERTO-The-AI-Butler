"""Unit and integration tests for production health & readiness probes."""

import pytest
from httpx import ASGITransport, AsyncClient

from alberto.main import app


@pytest.mark.asyncio
async def test_livez_liveness_probe():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/livez")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readyz_readiness_probe():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/readyz")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["ready"] is True
        checks = data["checks"]
        assert checks["db"] == "ok"
        assert checks["disk"] == "ok"
        assert "vector_store" in checks
        assert "graph_db" in checks
