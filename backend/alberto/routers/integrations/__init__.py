"""Domain package: alberto.routers.integrations."""

from __future__ import annotations

import importlib
import sys
from typing import Any


def __getattr__(name: str) -> Any:
    # Check submodules in alberto.routers.integrations
    submodules = ['channels', 'connections', 'connectors', 'hooks', 'mcp_clients', 'tools', 'tool_manager', 'tool_sets']
    if name in submodules:
        mod = importlib.import_module(f'alberto.routers.integrations.{name}')
        sys.modules[f'alberto.routers.integrations.{name}'] = mod
        globals()[name] = mod
        return mod
    # Check attributes across submodules
    for sub in submodules:
        mod = importlib.import_module(f'alberto.routers.integrations.{sub}')
        if hasattr(mod, name):
            val = getattr(mod, name)
            globals()[name] = val
            return val
    raise AttributeError(f"module 'alberto.routers.integrations' has no attribute '{name}'")
