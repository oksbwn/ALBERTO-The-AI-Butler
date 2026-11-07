"""Domain package: alberto.services.workflows."""

from __future__ import annotations

import importlib
import sys
from typing import Any

from alberto.services.workflows.workflows import WorkflowService

def __getattr__(name: str) -> Any:
    # Check submodules in alberto.services.workflows
    submodules = ['agents', 'assistant', 'automation_manager', 'components', 'conversations', 'dispatch', 'evals', 'handoff', 'runs', 'runtime', 'traces', 'triggers', 'workflows']
    if name in submodules:
        mod = importlib.import_module(f'alberto.services.workflows.{name}')
        sys.modules[f'alberto.services.workflows.{name}'] = mod
        globals()[name] = mod
        return mod
    # Check attributes across submodules
    for sub in submodules:
        mod = importlib.import_module(f'alberto.services.workflows.{sub}')
        if hasattr(mod, name):
            val = getattr(mod, name)
            globals()[name] = val
            return val
    raise AttributeError(f"module 'alberto.services.workflows' has no attribute '{name}'")
