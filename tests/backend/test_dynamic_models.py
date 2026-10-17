import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from alberto.engine.context import CompileContext
from alberto.engine.models import resolve_model
from alberto.main import create_app
from alberto.models.entities import ModelServer, RegisteredModel


@pytest.mark.asyncio
async def test_list_models_zero_phantom_rule():
    """Zero-Phantom Rule: No unconfigured cloud models appear in chat picker by default."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Without tenant auth or when no models registered, chat list is empty
        res = await client.get("/v1/models")
        assert res.status_code == 200
        data = res.json()
        assert "chat" in data
        assert "embedding" in data
        assert "reranker" in data
        # No phantom cloud models
        assert not any(m["id"] == "openai:gpt-4o" for m in data["chat"])


@pytest.mark.asyncio
async def test_model_registry_and_server_crud():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register user
        reg = await client.post(
            "/v1/auth/register",
            json={"email": f"u{uuid.uuid4().hex[:8]}@example.com", "password": "password123!"},
        )
        assert reg.status_code == 201
        token = reg.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"

        # 1. Initially servers and registry are empty
        res = await client.get("/v1/models/servers")
        assert res.status_code == 200
        assert res.json() == []

        res = await client.get("/v1/models/registry")
        assert res.status_code == 200
        assert res.json() == []

        # 2. Test server reachability test endpoint
        res = await client.post(
            "/v1/models/servers/test",
            json={"provider_type": "ollama", "base_url": "http://127.0.0.1:54321"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is False

        # 3. Create a model server (Ollama)
        res = await client.post(
            "/v1/models/servers",
            json={
                "name": "Local Ollama Engine",
                "provider_type": "ollama",
                "base_url": "http://localhost:11434",
                "enabled": True,
            },
        )
        assert res.status_code == 201
        server = res.json()
        server_id = server["id"]
        assert server["name"] == "Local Ollama Engine"
        assert server["provider_type"] == "ollama"

        # 4. List servers shows created server
        res = await client.get("/v1/models/servers")
        assert res.status_code == 200
        assert len(res.json()) == 1

        # 5. Register a model on this server
        res = await client.post(
            "/v1/models/registry",
            json={
                "server_id": server_id,
                "model_name": "llama3.2:latest",
                "display_name": "Home Butler Llama 3.2",
                "enabled": True,
                "context_window_configured": 32768,
                "temperature": 0.2,
                "top_p": 0.95,
                "max_output_tokens": 4096,
                "set_as_default": True,
            },
        )
        assert res.status_code == 201
        model = res.json()
        model_id = model["id"]
        assert model["display_name"] == "Home Butler Llama 3.2"
        assert model["is_default"] is True

        # 6. Unified consumer GET /v1/models now returns ONLY the registered model
        res = await client.get("/v1/models")
        assert res.status_code == 200
        cat = res.json()
        assert len(cat["chat"]) == 1
        assert cat["chat"][0]["id"] == model_id
        assert cat["chat"][0]["name"] == "Home Butler Llama 3.2"
        assert cat["chat"][0]["is_default"] is True

        # 7. Update model (change temperature and alias)
        res = await client.patch(
            f"/v1/models/registry/{model_id}",
            json={"display_name": "Home Butler Llama 3.2 (Fast)", "temperature": 0.1},
        )
        assert res.status_code == 200
        assert res.json()["display_name"] == "Home Butler Llama 3.2 (Fast)"
        assert res.json()["temperature"] == 0.1

        # 8. Deletion safety: deleting default model without force is rejected
        res = await client.delete(f"/v1/models/registry/{model_id}")
        assert res.status_code == 409

        # Deleting server with registered models without force is rejected
        res = await client.delete(f"/v1/models/servers/{server_id}")
        assert res.status_code == 409

        # Force delete model
        res = await client.delete(f"/v1/models/registry/{model_id}?force=true")
        assert res.status_code == 204

        # Model catalog is empty again
        res = await client.get("/v1/models")
        assert res.status_code == 200
        assert res.json()["chat"] == []

        # Delete server
        res = await client.delete(f"/v1/models/servers/{server_id}")
        assert res.status_code == 204


@pytest.mark.asyncio
async def test_resolve_model_with_registered_model():
    server = ModelServer(
        id="srv_local",
        tenant_id="t1",
        name="Ollama Local",
        provider_type="ollama",
        base_url="http://localhost:11434",
        enabled=True,
    )
    reg_model = RegisteredModel(
        id="mod_test_123",
        tenant_id="t1",
        server_id="srv_local",
        model_name="qwen2.5:latest",
        display_name="Qwen 2.5",
        enabled=True,
        temperature=0.15,
        top_p=0.85,
        max_output_tokens=2048,
    )

    ctx = CompileContext(
        tenant_id="t1",
        project_id="p1",
        registered_models={reg_model.id: reg_model},
        model_servers={server.id: server},
        default_model_id=reg_model.id,
    )

    # Resolve by ID
    llm = resolve_model("mod_test_123", ctx)
    assert getattr(llm, "model_name", None) == "qwen2.5:latest"
    assert getattr(llm, "temperature", None) == 0.15
    assert getattr(llm, "max_tokens", None) == 2048

    # Resolve default
    llm_def = resolve_model(None, ctx)
    assert getattr(llm_def, "model_name", None) == "qwen2.5:latest"


@pytest.mark.asyncio
async def test_resolve_model_disabled_raises_error():
    server = ModelServer(
        id="srv_off",
        tenant_id="t1",
        name="Offline Server",
        provider_type="ollama",
        base_url="http://localhost:11434",
        enabled=False,
    )
    reg_model = RegisteredModel(
        id="mod_disabled",
        tenant_id="t1",
        server_id="srv_off",
        model_name="llama3.2:latest",
        display_name="Disabled Llama",
        enabled=True,
    )
    ctx = CompileContext(
        tenant_id="t1",
        project_id="p1",
        registered_models={reg_model.id: reg_model},
        model_servers={server.id: server},
    )

    with pytest.raises(RuntimeError, match="disabled"):
        resolve_model("mod_disabled", ctx)
