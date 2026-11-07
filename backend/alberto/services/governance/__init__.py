"""Domain package: alberto.services.governance."""

from __future__ import annotations

import importlib
import sys
from typing import Any


def __getattr__(name: str) -> Any:
    # Check submodules in alberto.services.governance
    submodules = ['apikeys', 'audit', 'auth', 'auth_providers', 'budget', 'portability', 'projects', 'quota', 'retention', 'secrets', 'validation', 'versions']
    if name in submodules:
        mod = importlib.import_module(f'alberto.services.governance.{name}')
        sys.modules[f'alberto.services.governance.{name}'] = mod
        globals()[name] = mod
        return mod
    # Check attributes across submodules
    for sub in submodules:
        mod = importlib.import_module(f'alberto.services.governance.{sub}')
        if hasattr(mod, name):
            val = getattr(mod, name)
            globals()[name] = val
            return val
    raise AttributeError(f"module 'alberto.services.governance' has no attribute '{name}'")
