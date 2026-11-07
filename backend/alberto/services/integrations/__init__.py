"""Domain package: alberto.services.integrations."""

from __future__ import annotations

import importlib
import sys
from typing import Any


def __getattr__(name: str) -> Any:
    # Check submodules in alberto.services.integrations
    submodules = ['channels', 'channel_gateway', 'mcp_discovery', 'mcp_learning', 'tools', 'tool_manager', 'tool_policy', 'tool_sets']
    if name in submodules:
        mod = importlib.import_module(f'alberto.services.integrations.{name}')
        sys.modules[f'alberto.services.integrations.{name}'] = mod
        globals()[name] = mod
        return mod
    # Check attributes across submodules
    for sub in submodules:
        mod = importlib.import_module(f'alberto.services.integrations.{sub}')
        if hasattr(mod, name):
            val = getattr(mod, name)
            globals()[name] = val
            return val
    raise AttributeError(f"module 'alberto.services.integrations' has no attribute '{name}'")
