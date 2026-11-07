"""Domain package: alberto.routers.governance."""

from __future__ import annotations

import importlib
import sys
from typing import Any


def __getattr__(name: str) -> Any:
    # Check submodules in alberto.routers.governance
    submodules = ['audit', 'auth', 'auth_providers', 'health', 'models', 'oauth', 'projects', 'secrets', 'stats', 'versions']
    if name in submodules:
        mod = importlib.import_module(f'alberto.routers.governance.{name}')
        sys.modules[f'alberto.routers.governance.{name}'] = mod
        globals()[name] = mod
        return mod
    # Check attributes across submodules
    for sub in submodules:
        mod = importlib.import_module(f'alberto.routers.governance.{sub}')
        if hasattr(mod, name):
            val = getattr(mod, name)
            globals()[name] = val
            return val
    raise AttributeError(f"module 'alberto.routers.governance' has no attribute '{name}'")
