#!/usr/bin/env python3
"""OpenAPI Schema to Markdown API Reference Generator for Alberto Documentation.

Reads `openapi_dump.json` (or live schema) and produces structured documentation pages:
- docs/api/index.md
- docs/api/auth.md
- docs/api/agents.md
- docs/api/chat.md
- docs/api/models.md
- docs/api/tools-and-integrations.md
- docs/api/memory-and-knowledge.md
- docs/api/workflows.md
- docs/api/system.md
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_API_DIR = REPO_ROOT / "docs" / "api"
OPENAPI_PATH = REPO_ROOT / "openapi_dump.json"

TAG_TO_FILE = {
    "auth": "auth.md",
    "auth-providers": "auth.md",
    "oauth": "auth.md",
    "agents": "agents.md",
    "assistant": "chat.md",
    "conversations": "chat.md",
    "models": "models.md",
    "catalog": "models.md",
    "tools": "tools-and-integrations.md",
    "tool-manager": "tools-and-integrations.md",
    "tool-sets": "tools-and-integrations.md",
    "mcp-clients": "tools-and-integrations.md",
    "connectors": "tools-and-integrations.md",
    "connections": "tools-and-integrations.md",
    "channels": "tools-and-integrations.md",
    "integration-manager": "tools-and-integrations.md",
    "knowledge": "memory-and-knowledge.md",
    "memory": "memory-and-knowledge.md",
    "graph": "memory-and-knowledge.md",
    "workflows": "workflows.md",
    "automate": "workflows.md",
    "runs": "workflows.md",
    "project-run": "workflows.md",
    "triggers": "workflows.md",
    "components": "workflows.md",
    "health": "system.md",
    "stats": "system.md",
    "traces": "system.md",
    "audit": "system.md",
    "secrets": "system.md",
    "versions": "system.md",
    "evals": "system.md",
    "hooks": "system.md",
    "handoff": "system.md",
    "meta": "system.md",
    "team": "system.md",
    "workspace": "system.md",
    "projects": "system.md",
}

PAGE_TITLES = {
    "auth.md": ("Authentication & Authorization API", "Endpoints for user registration, JWT lifecycle, password reset, MFA, and OAuth providers."),
    "agents.md": ("Agents & Specialists API", "Endpoints for defining, inspecting, updating, and delegating to specialist agent configurations."),
    "chat.md": ("Assistant & Conversation API", "Endpoints for interactive Butler sessions, streaming responses, and conversation threads."),
    "models.md": ("Model Catalog & Providers API", "Endpoints for discovered LLMs, provider registrations, pricing, and active assignments."),
    "tools-and-integrations.md": ("Tools & Integrations API", "Endpoints for Tool Manager, MCP clients, REST connectors, and channel bindings."),
    "memory-and-knowledge.md": ("Memory & Knowledge API", "Endpoints for document ingestion, Chroma vector retrieval, and Knowledge Graph entities."),
    "workflows.md": ("Automate & Workflows API", "Endpoints for visual canvas workflows, step execution, triggers, and runs."),
    "system.md": ("System, Diagnostics & Administration API", "Endpoints for platform health, audit telemetry, evaluations, and projects."),
}


def load_openapi() -> dict:
    if not OPENAPI_PATH.exists():
        raise FileNotFoundError(f"Missing OpenAPI schema at {OPENAPI_PATH}")
    with open(OPENAPI_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def format_schema(schema: dict) -> str:
    if not schema:
        return "None"
    if "$ref" in schema:
        ref_name = schema["$ref"].split("/")[-1]
        return f"`{ref_name}`"
    schema_type = schema.get("type", "object")
    if schema_type == "array":
        items = schema.get("items", {})
        item_type = format_schema(items)
        return f"list of {item_type}"
    return f"`{schema_type}`"


def render_endpoint(path: str, method: str, op: dict) -> str:
    summary = op.get("summary") or op.get("operationId") or f"{method.upper()} {path}"
    desc = op.get("description", "").strip()
    tags = op.get("tags", [])
    
    md = [f"### `{method.upper()}` {path}\n"]
    md.append(f"**{summary}**\n")
    if desc:
        md.append(f"{desc}\n")
    
    # Parameters
    params = op.get("parameters", [])
    if params:
        md.append("#### Parameters\n")
        md.append("| Name | In | Type | Required | Description |")
        md.append("| :--- | :--- | :--- | :--- | :--- |")
        for p in params:
            name = p.get("name", "")
            pin = p.get("in", "")
            req = "Yes" if p.get("required") else "No"
            ptype = format_schema(p.get("schema", {}))
            pdesc = p.get("description", "").replace("\n", " ").strip()
            md.append(f"| `{name}` | {pin} | {ptype} | {req} | {pdesc} |")
        md.append("")

    # Request Body
    req_body = op.get("requestBody", {})
    if req_body:
        content = req_body.get("content", {})
        for ctype, cval in content.items():
            schema_fmt = format_schema(cval.get("schema", {}))
            md.append(f"#### Request Body (`{ctype}`)\n")
            md.append(f"Schema: {schema_fmt}\n")

    # Responses
    responses = op.get("responses", {})
    if responses:
        md.append("#### Responses\n")
        md.append("| Status | Description | Schema |")
        md.append("| :--- | :--- | :--- |")
        for status, rinfo in responses.items():
            rdesc = rinfo.get("description", "").replace("\n", " ").strip()
            content = rinfo.get("content", {})
            rschema = "None"
            for ctype, cval in content.items():
                rschema = f"`{ctype}`: {format_schema(cval.get('schema', {}))}"
                break
            md.append(f"| `{status}` | {rdesc} | {rschema} |")
        md.append("")

    md.append("---\n")
    return "\n".join(md)


def main():
    schema = load_openapi()
    DOCS_API_DIR.mkdir(parents=True, exist_ok=True)
    
    pages: dict[str, list[tuple[str, str, dict]]] = {f: [] for f in PAGE_TITLES}
    
    for path, methods in schema.get("paths", {}).items():
        for method, op in methods.items():
            if method.lower() not in ("get", "post", "put", "delete", "patch"):
                continue
            tags = op.get("tags", [])
            primary_tag = tags[0] if tags else "system"
            target_file = TAG_TO_FILE.get(primary_tag, "system.md")
            if target_file in pages:
                pages[target_file].append((path, method, op))

    # Generate each target page
    for filename, (title, subtitle) in PAGE_TITLES.items():
        endpoints = pages[filename]
        content = [
            f"# {title}\n",
            f"{subtitle}\n",
            f"> [!NOTE]\n> Total verified endpoints documented: **{len(endpoints)}**.\n",
        ]
        
        for path, method, op in sorted(endpoints, key=lambda x: (x[0], x[1])):
            content.append(render_endpoint(path, method, op))
            
        file_path = DOCS_API_DIR / filename
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(content))
        print(f"Generated {filename}: {len(endpoints)} endpoints")

    # Index page
    total_endpoints = sum(len(e) for e in pages.values())
    index_md = [
        "# API Reference Overview\n",
        "Alberto exposes a complete, OpenAPI 3.1-compliant REST API powered by FastAPI. "
        "Every endpoint conforms to strict Pydantic schemas with type enforcement, JWT authentication, "
        "and granular project/tenant isolation.\n",
        "## Base URLs\n",
        "- **Development Server**: `http://127.0.0.1:8000`",
        "- **Production Container**: `http://localhost:8000`",
        "- **OpenAPI Specification**: `http://127.0.0.1:8000/openapi.json`",
        "- **Interactive Swagger UI**: `http://127.0.0.1:8000/api/docs`",
        "- **Interactive ReDoc**: `http://127.0.0.1:8000/api/redoc`\n",
        "## Authentication\n",
        "Endpoints require a Bearer JWT passed in the HTTP `Authorization` header:",
        "```http",
        "Authorization: Bearer <your_access_token>",
        "```\n",
        "Tokens are obtained via `/v1/auth/login` and refreshed through `/v1/auth/refresh`.\n",
        "## Subsystem API Guides\n",
        f"Verified total endpoints in active schema: **{total_endpoints}**.\n",
        "| Section | Endpoints | Description |",
        "| :--- | :--- | :--- |",
    ]
    for filename, (title, subtitle) in PAGE_TITLES.items():
        ep_count = len(pages[filename])
        index_md.append(f"| [{title}]({filename}) | {ep_count} | {subtitle} |")
    
    with open(DOCS_API_DIR / "index.md", "w", encoding="utf-8") as f:
        f.write("\n".join(index_md))
    print(f"Generated docs/api/index.md (total endpoints: {total_endpoints})")


if __name__ == "__main__":
    main()
