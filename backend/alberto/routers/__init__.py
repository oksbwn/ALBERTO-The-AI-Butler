"""HTTP + SSE routers.

Organized by domain:
- workflows: agents, assistant, automate, components, conversations, evals, handoff, nodes, project_run, runs, traces, triggers, workflows
- memory: graph, knowledge, memory
- integrations: channels, connections, connectors, hooks, mcp_clients, tools, tool_manager, tool_sets
- governance: audit, auth, auth_providers, health, models, oauth, projects, secrets, stats, versions
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import Any

# PEP 302/420 path extension: allows Python's import loader to locate submodules
# directly inside domain directories (e.g. `alberto.routers.runs`).
_pkg_dir = os.path.dirname(__file__)
for _sub in ("workflows", "memory", "integrations", "governance"):
    _sub_path = os.path.join(_pkg_dir, _sub)
    if os.path.isdir(_sub_path) and _sub_path not in __path__:
        __path__.append(_sub_path)

# Domain mapping for fast lookup and attribute access
ROUTER_MAP: dict[str, str] = {
    # workflows
    "agents": "workflows",
    "assistant": "workflows",
    "automate": "workflows",
    "components": "workflows",
    "conversations": "workflows",
    "evals": "workflows",
    "handoff": "workflows",
    "nodes": "workflows",
    "project_run": "workflows",
    "runs": "workflows",
    "traces": "workflows",
    "triggers": "workflows",
    "workflows": "workflows",
    # memory
    "graph": "memory",
    "knowledge": "memory",
    "memory": "memory",
    # integrations
    "channels": "integrations",
    "connections": "integrations",
    "connectors": "integrations",
    "hooks": "integrations",
    "mcp_clients": "integrations",
    "tools": "integrations",
    "tool_manager": "integrations",
    "tool_sets": "integrations",
    # governance
    "audit": "governance",
    "auth": "governance",
    "auth_providers": "governance",
    "health": "governance",
    "models": "governance",
    "oauth": "governance",
    "projects": "governance",
    "secrets": "governance",
    "stats": "governance",
    "versions": "governance",
}


def __getattr__(name: str) -> Any:
    if name in ROUTER_MAP:
        domain = ROUTER_MAP[name]
        mod = importlib.import_module(f"alberto.routers.{domain}.{name}")
        sys.modules[f"alberto.routers.{name}"] = mod
        globals()[name] = mod
        return mod
    if name in ("workflows", "memory", "integrations", "governance"):
        mod = importlib.import_module(f"alberto.routers.{name}")
        globals()[name] = mod
        return mod
    raise AttributeError(f"module 'alberto.routers' has no attribute '{name}'")


def __dir__() -> list[str]:
    return list(globals().keys()) + list(ROUTER_MAP.keys()) + ["workflows", "memory", "integrations", "governance"]
