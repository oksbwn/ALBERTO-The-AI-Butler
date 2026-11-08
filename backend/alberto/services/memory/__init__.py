"""Domain package: alberto.services.memory."""

from __future__ import annotations

import importlib
import sys
from typing import Any

from alberto.services.memory.memory import MemoryService as MemoryService

__all__ = ["MemoryService"]


def __getattr__(name: str) -> Any:
    # Check submodules in alberto.services.memory
    submodules = ['context_assembler', 'graph_manager', 'knowledge', 'learning_coordinator', 'markdown_memory', 'memory', 'memory_curator', 'ontology_registry', 'retrieval_policy', 'semantic_cache', 'source_sync', 'unified_memory']
    if name in submodules:
        mod = importlib.import_module(f'alberto.services.memory.{name}')
        sys.modules[f'alberto.services.memory.{name}'] = mod
        globals()[name] = mod
        return mod
    # Check attributes across submodules
    for sub in submodules:
        mod = importlib.import_module(f'alberto.services.memory.{sub}')
        if hasattr(mod, name):
            val = getattr(mod, name)
            globals()[name] = val
            return val
    raise AttributeError(f"module 'alberto.services.memory' has no attribute '{name}'")
