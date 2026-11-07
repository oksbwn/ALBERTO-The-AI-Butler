"""Domain package: alberto.routers.workflows."""

from __future__ import annotations

import importlib
import sys
from typing import Any

from alberto.routers.workflows.workflows import router

def __getattr__(name: str) -> Any:
    # Check submodules in alberto.routers.workflows
    submodules = ['agents', 'assistant', 'automate', 'components', 'conversations', 'evals', 'handoff', 'nodes', 'project_run', 'runs', 'traces', 'triggers', 'workflows']
    if name in submodules:
        mod = importlib.import_module(f'alberto.routers.workflows.{name}')
        sys.modules[f'alberto.routers.workflows.{name}'] = mod
        globals()[name] = mod
        return mod
    # Check attributes across submodules
    for sub in submodules:
        mod = importlib.import_module(f'alberto.routers.workflows.{sub}')
        if hasattr(mod, name):
            val = getattr(mod, name)
            globals()[name] = val
            return val
    raise AttributeError(f"module 'alberto.routers.workflows' has no attribute '{name}'")
