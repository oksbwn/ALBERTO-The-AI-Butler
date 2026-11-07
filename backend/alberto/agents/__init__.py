"""Decoupled Built-in Sub-Agents Package for Alberto."""

from alberto.agents.base import AgentSpec, load_agent_markdown
from alberto.agents.router import AgentRouter

__all__ = ["AgentRouter", "AgentSpec", "load_agent_markdown"]

