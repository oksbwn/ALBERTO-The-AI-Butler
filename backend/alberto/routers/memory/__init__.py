"""Domain package: alberto.routers.memory."""

from __future__ import annotations

import importlib
import sys
from typing import Any

from alberto.routers.memory.memory import router as router

__all__ = ["router"]


def __getattr__(name: str) -> Any:
    # Check submodules in alberto.routers.memory
    submodules = ['graph', 'knowledge', 'memory']
    if name in submodules:
        mod = importlib.import_module(f'alberto.routers.memory.{name}')
        sys.modules[f'alberto.routers.memory.{name}'] = mod
        globals()[name] = mod
        return mod
    # Check attributes across submodules
    for sub in submodules:
        mod = importlib.import_module(f'alberto.routers.memory.{sub}')
        if hasattr(mod, name):
            val = getattr(mod, name)
            globals()[name] = val
            return val
    raise AttributeError(f"module 'alberto.routers.memory' has no attribute '{name}'")
