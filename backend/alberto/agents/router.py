"""Persona & Intent Router for Alberto's decoupled built-in sub-agents."""

from __future__ import annotations

from pathlib import Path

from alberto.agents.automation_manager import build_automation_manager_spec
from alberto.agents.base import AgentSpec
from alberto.agents.butler import build_butler_spec
from alberto.agents.graph_manager import build_graph_manager_spec
from alberto.agents.intent_router import build_intent_router_spec
from alberto.agents.memory_curator import build_memory_curator_spec
from alberto.agents.tool_manager import build_tool_manager_spec


class AgentRouter:
    """Registry and router that resolves a persona or user request to its decoupled AgentSpec."""

    _SPECS: list[AgentSpec] = [
        build_butler_spec(),
        build_automation_manager_spec(),
        build_tool_manager_spec(),
        build_memory_curator_spec(),
        build_graph_manager_spec(),
        build_intent_router_spec(),
    ]

    _BY_ID: dict[str, AgentSpec] = {}
    for _spec in _SPECS:
        _BY_ID[_spec.id] = _spec
        for _alias in _spec.aliases:
            _BY_ID[_alias] = _spec

    @classmethod
    def resolve(cls, persona: str | None = None, user_msg: str = "") -> AgentSpec:
        """Resolve an explicit persona or fallback to a dynamically constructed sub-agent spec."""
        key = (persona or "").strip().lower()
        if key in cls._BY_ID:
            return cls._BY_ID[key]

        # Generic fallback for any custom/future persona identifier
        clean_name = key.replace("_", " ").title()
        fallback_dir = Path(__file__).resolve().parent / key
        spec = AgentSpec(
            id=key,
            display_name=clean_name,
            trace_name="assistant",
            actor_name="System",
            agent_dir=fallback_dir,
            recall_top_k=5,
        )
        return spec

    @classmethod
    def get_system_prompt(cls, spec: AgentSpec) -> str:
        """Return the system prompt from the agent's prompt.md (or fallback for custom personas)."""
        prompt = spec.get_prompt()
        if prompt:
            return prompt
        return (
            f"You are Alberto's {spec.display_name} Sub-Agent. "
            "Be natural, helpful, and concise. Answer questions directly using recalled context."
        )

    @classmethod
    def list_agents(cls) -> list[AgentSpec]:
        """Return all registered built-in AgentSpecs."""
        return list(cls._SPECS)

