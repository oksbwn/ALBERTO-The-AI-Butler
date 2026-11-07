"""Memory Curator Sub-Agent specification."""

from __future__ import annotations

from pathlib import Path

from alberto.agents.base import AgentSpec

AGENT_DIR = Path(__file__).resolve().parent


def build_memory_curator_spec() -> AgentSpec:
    return AgentSpec(
        id="memory_curator",
        display_name="Memory Curator",
        trace_name="memory_curator",
        actor_name="Memory Curator",
        agent_dir=AGENT_DIR,
        aliases=("memory", "memorycurator"),
        recall_top_k=8,
    )

