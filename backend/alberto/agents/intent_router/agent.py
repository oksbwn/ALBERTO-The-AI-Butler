"""Intent Router Sub-Agent specification and lightweight intent classification."""

from __future__ import annotations

from pathlib import Path

from alberto.agents.base import AgentSpec

AGENT_DIR = Path(__file__).resolve().parent


def classify_user_intent(user_msg: str) -> str:
    """Classify a user prompt into a specialist domain when no explicit persona is set."""
    low = (user_msg or "").strip().lower()
    if not low:
        return "assistant"
    if any(
        k in low
        for k in (
            "build a workflow",
            "create a workflow",
            "design a workflow",
            "generate a workflow",
            "new workflow",
            "workflow proposal",
        )
    ):
        return "automation_manager"
    return "assistant"


def build_intent_router_spec() -> AgentSpec:
    return AgentSpec(
        id="intent_router",
        display_name="Intent Router",
        trace_name="assistant",
        actor_name="System",
        agent_dir=AGENT_DIR,
        aliases=("router", "intentrouter"),
        recall_top_k=5,
    )

