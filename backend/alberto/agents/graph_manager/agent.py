"""Knowledge Graph Manager Sub-Agent specification."""

from __future__ import annotations

from pathlib import Path

from alberto.agents.base import AgentSpec

AGENT_DIR = Path(__file__).resolve().parent


def build_graph_manager_spec() -> AgentSpec:
    return AgentSpec(
        id="graph_manager",
        display_name="Knowledge Graph Manager",
        trace_name="assistant",
        actor_name="System",
        agent_dir=AGENT_DIR,
        aliases=("graph", "graphmanager", "knowledge_graph"),
        recall_top_k=6,
    )

