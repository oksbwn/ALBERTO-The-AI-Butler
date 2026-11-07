"""Base abstractions and markdown loaders for Alberto's decoupled built-in agents."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def load_agent_markdown(agent_dir: Path, filename: str, default: str = "") -> str:
    """Load a markdown file (e.g. prompt.md or skills.md) from an agent's directory."""
    path = agent_dir / filename
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return default


@dataclass
class AgentSpec:
    """Declarative specification for a built-in Alberto sub-agent."""

    id: str
    display_name: str
    trace_name: str
    actor_name: str
    agent_dir: Path
    aliases: tuple[str, ...] = field(default_factory=tuple)
    recall_top_k: int = 5
    include_skills_in_fast_prompt: bool = False
    _select_tools_fn: Callable[[list[Any], str], list[Any]] | None = None
    _build_context_fn: Callable[[Any, str, str], Any] | None = None
    _post_turn_fallback_fn: Callable[..., AsyncIterator[dict]] | None = None

    def get_prompt(self) -> str:
        """Load the primary system prompt from prompt.md."""
        prompt = load_agent_markdown(self.agent_dir, "prompt.md")
        if self.include_skills_in_fast_prompt:
            skills = self.get_skills()
            if skills:
                return f"{prompt}\n\n{skills}"
        return prompt

    def get_skills(self) -> str:
        """Load the agent's specialized skills documentation from skills.md."""
        return load_agent_markdown(self.agent_dir, "skills.md")

    def select_tools(self, all_tools: list[Any], user_msg: str = "") -> list[Any]:
        """Filter the platform tools bound to this agent."""
        if self._select_tools_fn is not None:
            return self._select_tools_fn(all_tools, user_msg)
        return []

    async def build_live_context(self, session: Any, tenant_id: str, project_id: str) -> str:
        """Assemble live project registry context (workflows, MCP servers, graph stats, etc.)."""
        if self._build_context_fn is not None:
            return await self._build_context_fn(session, tenant_id, project_id)
        return ""

    async def run_post_turn_fallback(
        self,
        *,
        user_msg: str,
        tools_to_bind: list[Any],
        mutated: list[Any],
        final_text: str,
    ) -> AsyncIterator[dict]:
        """Optional fallback hook executed when a fast-stream model omits a required tool call."""
        if self._post_turn_fallback_fn is not None:
            async for frame in self._post_turn_fallback_fn(
                user_msg=user_msg,
                tools_to_bind=tools_to_bind,
                mutated=mutated,
                final_text=final_text,
            ):
                yield frame

