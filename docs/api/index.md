# API Reference Overview

Alberto exposes a complete, OpenAPI 3.1-compliant REST API powered by FastAPI. Every endpoint conforms to strict Pydantic schemas with type enforcement, JWT authentication, and granular project/tenant isolation.

## Base URLs

- **Development Server**: `http://127.0.0.1:8000`
- **Production Container**: `http://localhost:8000`
- **OpenAPI Specification**: `http://127.0.0.1:8000/openapi.json`
- **Interactive Swagger UI**: `http://127.0.0.1:8000/api/docs`
- **Interactive ReDoc**: `http://127.0.0.1:8000/api/redoc`

## Authentication

Endpoints require a Bearer JWT passed in the HTTP `Authorization` header:
```http
Authorization: Bearer <your_access_token>
```

Tokens are obtained via `/v1/auth/login` and refreshed through `/v1/auth/refresh`.

## Subsystem API Guides

Verified total endpoints in active schema: **268**.

| Section | Endpoints | Description |
| :--- | :--- | :--- |
| [Authentication & Authorization API](auth.md) | 28 | Endpoints for user registration, JWT lifecycle, password reset, MFA, and OAuth providers. |
| [Agents & Specialists API](agents.md) | 8 | Endpoints for defining, inspecting, updating, and delegating to specialist agent configurations. |
| [Assistant & Conversation API](chat.md) | 6 | Endpoints for interactive Butler sessions, streaming responses, and conversation threads. |
| [Model Catalog & Providers API](models.md) | 18 | Endpoints for discovered LLMs, provider registrations, pricing, and active assignments. |
| [Tools & Integrations API](tools-and-integrations.md) | 67 | Endpoints for Tool Manager, MCP clients, REST connectors, and channel bindings. |
| [Memory & Knowledge API](memory-and-knowledge.md) | 46 | Endpoints for document ingestion, Chroma vector retrieval, and Knowledge Graph entities. |
| [Automate & Workflows API](workflows.md) | 51 | Endpoints for visual canvas workflows, step execution, triggers, and runs. |
| [System, Diagnostics & Administration API](system.md) | 44 | Endpoints for platform health, audit telemetry, evaluations, and projects. |