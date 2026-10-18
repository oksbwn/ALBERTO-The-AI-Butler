import pytest
from httpx import ASGITransport, AsyncClient
from alberto.main import app
from alberto.knowledge.embeddings import check_embedding_model_status


@pytest.mark.asyncio
async def test_check_embedding_model_status_hosted():
    status = check_embedding_model_status("openai:text-embedding-3-small")
    assert status["is_local"] is False
    assert status["cached"] is True


@pytest.mark.asyncio
async def test_check_embedding_model_status_local():
    status = check_embedding_model_status("fastembed:BAAI/bge-small-en-v1.5")
    assert status["is_local"] is True
    assert "data/models/fastembed" in status["cache_dir"].replace("\\", "/")


@pytest.mark.asyncio
async def test_embedding_status_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/v1/models/embeddings/status?model_id=openai:text-embedding-3-small")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_local"] is False
        assert data["cached"] is True

        resp_local = await ac.get("/v1/models/embeddings/status?model_id=fastembed:BAAI/bge-small-en-v1.5")
        assert resp_local.status_code == 200
        data_local = resp_local.json()
        assert data_local["is_local"] is True
