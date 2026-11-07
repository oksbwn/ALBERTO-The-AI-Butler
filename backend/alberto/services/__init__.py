"""Service layer - business logic between routers and the engine/persistence.

Organized by domain:
- workflows: agents, assistant, automation_manager, components, conversations, dispatch, evals, handoff, runs, runtime, traces, triggers, workflows
- memory: context_assembler, graph_manager, knowledge, learning_coordinator, markdown_memory, memory, memory_curator, ontology_registry, retrieval_policy, semantic_cache, source_sync, unified_memory
- integrations: channels, channel_gateway, mcp_discovery, mcp_learning, tools, tool_manager, tool_policy, tool_sets
- governance: apikeys, audit, auth, auth_providers, budget, portability, projects, quota, retention, secrets, validation, versions
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import Any

# PEP 302/420 path extension: allows Python's import loader to locate submodules
# directly inside domain directories (e.g. `alberto.services.runs`).
_pkg_dir = os.path.dirname(__file__)
for _sub in ("workflows", "memory", "integrations", "governance"):
    _sub_path = os.path.join(_pkg_dir, _sub)
    if os.path.isdir(_sub_path) and _sub_path not in __path__:
        __path__.append(_sub_path)

# Domain mapping for fast lookup and attribute access
SERVICE_MAP: dict[str, str] = {
    # workflows
    "agents": "workflows",
    "assistant": "workflows",
    "automation_manager": "workflows",
    "components": "workflows",
    "conversations": "workflows",
    "dispatch": "workflows",
    "evals": "workflows",
    "handoff": "workflows",
    "runs": "workflows",
    "runtime": "workflows",
    "traces": "workflows",
    "triggers": "workflows",
    "workflows": "workflows",
    # memory
    "context_assembler": "memory",
    "graph_manager": "memory",
    "knowledge": "memory",
    "learning_coordinator": "memory",
    "markdown_memory": "memory",
    "memory": "memory",
    "memory_curator": "memory",
    "ontology_registry": "memory",
    "retrieval_policy": "memory",
    "semantic_cache": "memory",
    "source_sync": "memory",
    "unified_memory": "memory",
    # integrations
    "channels": "integrations",
    "channel_gateway": "integrations",
    "mcp_clients": "integrations",
    "mcp_discovery": "integrations",
    "mcp_learning": "integrations",
    "tools": "integrations",
    "tool_manager": "integrations",
    "tool_policy": "integrations",
    "tool_sets": "integrations",
    # governance
    "apikeys": "governance",
    "audit": "governance",
    "auth": "governance",
    "auth_providers": "governance",
    "budget": "governance",
    "models": "governance",
    "portability": "governance",
    "projects": "governance",
    "quota": "governance",
    "retention": "governance",
    "secrets": "governance",
    "stats": "governance",
    "validation": "governance",
    "versions": "governance",
}


def __getattr__(name: str) -> Any:
    if name in SERVICE_MAP:
        domain = SERVICE_MAP[name]
        mod = importlib.import_module(f"alberto.services.{domain}.{name}")
        sys.modules[f"alberto.services.{name}"] = mod
        globals()[name] = mod
        return mod
    if name in ("workflows", "memory", "integrations", "governance"):
        mod = importlib.import_module(f"alberto.services.{name}")
        globals()[name] = mod
        return mod
    raise AttributeError(f"module 'alberto.services' has no attribute '{name}'")


def __dir__() -> list[str]:
    return list(globals().keys()) + list(SERVICE_MAP.keys()) + ["workflows", "memory", "integrations", "governance"]
