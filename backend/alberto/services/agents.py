"""Agent preset CRUD. Config validates against the agent node schema (forge/nodes/agent)."""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.models import Agent
from alberto.schemas.contracts import validate_against_id

INTEGRATION_MANAGER_DESCRIPTION = (
    "Discovers, classifies, recommends and diagnoses integrations, communication channels and tools; "
    "mediates authorised external tool execution for the Master Agent."
)

SYSTEM_AGENT_SPECS: dict[str, dict[str, Any]] = {
    "intent_router": {
        "name": "Intent Router",
        "system_key": "intent_router",
        "description": "Determines and routes user intent using Alberto's routing engine.",
        "config": {
            "name": "intent_router",
            "description": "Determines and routes user intent using Alberto's routing engine.",
            "system_prompt": "You are the Intent Router for Alberto.",
            "tools": [],
            "model": "",
            "status": "active",
            "routing_mode": "deterministic",
        },
    },
    "memory_curator": {
        "name": "Memory Curator",
        "system_key": "memory_curator",
        "description": "Curates, summarizes, and organizes durable memory records. Inactive until Milestone 2.1.",
        "config": {
            "name": "memory_curator",
            "description": "Curates, summarizes, and organizes durable memory records. Inactive until Milestone 2.1.",
            "system_prompt": "You are the Memory Curator for Alberto.",
            "tools": [],
            "model": "",
            "status": "inactive",
        },
    },
    "graph_manager": {
        "name": "Graph Manager",
        "system_key": "graph_manager",
        "description": "Manages entities and relationships in Alberto's Knowledge Graph. Inactive until Milestone 2.1.",
        "config": {
            "name": "graph_manager",
            "description": "Manages entities and relationships in Alberto's Knowledge Graph. Inactive until Milestone 2.1.",
            "system_prompt": "You are the Graph Manager for Alberto.",
            "tools": [],
            "model": "",
            "status": "inactive",
        },
    },
    # Integrations v3: this is the Integration Manager. The internal identifier stays
    # `tool_manager` (system_key, config.name, caller_type, delegate_tool_execution, routes) so
    # persisted model overrides, traces and permissions survive; only the display name changed.
    "tool_manager": {
        "name": "Integration Manager",
        "system_key": "tool_manager",
        "description": INTEGRATION_MANAGER_DESCRIPTION,
        "config": {
            "name": "tool_manager",
            "description": INTEGRATION_MANAGER_DESCRIPTION,
            "system_prompt": "You are Alberto's Integration Manager. You understand installed integrations, MCP servers, communication channels and tools: analyze capabilities and schemas, classify effects and risk, recommend suitable capabilities, diagnose connection, authentication and delivery failures, and mediate authorised tool execution for the Master Agent. You never grant permissions, approve operations or change credentials yourself.",
            "tools": [],
            "model": "",
            "status": "active",
        },
    },
}

# Pre-v3 display names / prompts, used to migrate existing rows in place (never duplicating them).
LEGACY_SYSTEM_AGENT_NAMES = {"tool_manager": "Tool Manager"}
LEGACY_TOOL_MANAGER_PROMPT = "You are Alberto's Tool Manager. You analyze tool capabilities, schemas, effect classification, and suggest suitable tools."
LEGACY_TOOL_MANAGER_DESCRIPTION = "Analyzes discovered tools, classifies risk and effects, detects duplicate capabilities, and recommends activations."

RESERVED_SYSTEM_KEYS = set(SYSTEM_AGENT_SPECS.keys())


class AgentService:
    @staticmethod
    async def ensure_system_agents(
        session: AsyncSession, tenant_id: str, project_id: str
    ) -> list[Agent]:
        """Idempotently provisions built-in system agents for (tenant_id, project_id).
        Preserves existing user overrides (e.g. model selection) on restart."""
        existing = await session.execute(
            select(Agent).where(
                Agent.tenant_id == tenant_id,
                Agent.project_id == project_id,
                Agent.is_system.is_(True),
            )
        )
        existing_by_key = {a.system_key: a for a in existing.scalars() if a.system_key}

        # Integrations v3: Tool Manager -> Integration Manager, migrated in place (same row/id).
        renamed = False
        for key, legacy_name in LEGACY_SYSTEM_AGENT_NAMES.items():
            row = existing_by_key.get(key)
            if row is None or row.name != legacy_name:
                continue
            spec = SYSTEM_AGENT_SPECS[key]
            row.name = spec["name"]
            cfg = copy.deepcopy(row.config or {})
            if cfg.get("description") in (None, "", LEGACY_TOOL_MANAGER_DESCRIPTION):
                cfg["description"] = spec["config"]["description"]
            if cfg.get("system_prompt") in (None, "", LEGACY_TOOL_MANAGER_PROMPT):
                cfg["system_prompt"] = spec["config"]["system_prompt"]
            row.config = cfg
            renamed = True
        if renamed:
            await session.commit()

        created = []
        for key, spec in SYSTEM_AGENT_SPECS.items():
            if key in existing_by_key:
                continue

            # Ensure no collision with agent using this exact system_key
            collision = (
                await session.execute(
                    select(Agent).where(
                        Agent.tenant_id == tenant_id,
                        Agent.project_id == project_id,
                        Agent.system_key == key,
                    )
                )
            ).scalar_one_or_none()

            if collision:
                collision.is_system = True
                continue

            agent = Agent(
                tenant_id=tenant_id,
                project_id=project_id,
                name=spec["name"],
                is_system=True,
                system_key=key,
                config=copy.deepcopy(spec["config"]),
                created_by=None,
                created_by_email="system@alberto.local",
            )
            session.add(agent)
            created.append(agent)

        if created:
            try:
                await session.commit()
                for a in created:
                    await session.refresh(a)
            except IntegrityError:
                await session.rollback()

        all_agents = await session.execute(
            select(Agent).where(
                Agent.tenant_id == tenant_id,
                Agent.project_id == project_id,
                Agent.is_system.is_(True),
            )
        )
        return [a for a in all_agents.scalars()]

    @staticmethod
    async def list(session: AsyncSession, tenant_id: str, project_id: str) -> list[Agent]:
        await AgentService.ensure_system_agents(session, tenant_id, project_id)
        rows = await session.execute(
            select(Agent)
            .where(Agent.tenant_id == tenant_id, Agent.project_id == project_id)
            .order_by(Agent.is_system.asc(), Agent.created_at.asc())
        )
        return [a for a in rows.scalars()]

    @staticmethod
    async def get(session: AsyncSession, tenant_id: str, agent_id: str) -> Agent | None:
        row = await session.execute(select(Agent).where(Agent.tenant_id == tenant_id, Agent.id == agent_id))
        return row.scalar_one_or_none()

    @staticmethod
    def validate(config: dict) -> list[dict]:
        return validate_against_id(config, "forge/nodes/agent")

    @staticmethod
    async def create(session: AsyncSession, tenant_id: str, project_id: str, *, name: str, config: dict,
                     created_by: str | None = None, created_by_email: str | None = None,
                     is_system: bool = False, system_key: str | None = None) -> Agent:
        if system_key in RESERVED_SYSTEM_KEYS and not is_system:
            raise ValueError(f"Cannot create user agent with reserved system key '{system_key}'")
        if name in {s["name"] for s in SYSTEM_AGENT_SPECS.values()} and not is_system:
            raise ValueError(f"Agent name '{name}' is reserved for built-in system agents")
        if is_system and system_key not in RESERVED_SYSTEM_KEYS:
            raise ValueError(f"Unknown system key '{system_key}'")

        agent = Agent(tenant_id=tenant_id, project_id=project_id, name=name, config=config or {},
                      created_by=created_by, created_by_email=created_by_email,
                      is_system=is_system, system_key=system_key)
        session.add(agent)
        await session.commit()
        await session.refresh(agent)
        return agent

    @staticmethod
    async def delete(session: AsyncSession, agent: Agent) -> None:
        if agent.is_system:
            raise ValueError("Protected system agents cannot be deleted.")
        await session.delete(agent)
        await session.commit()

    @staticmethod
    async def update(session: AsyncSession, agent: Agent, *, name: str | None = None, config: dict | None = None) -> Agent:
        if agent.is_system:
            # Protected: cannot rename the identity of system agents
            if name is not None and name != agent.name:
                raise ValueError("Protected system agents cannot be renamed.")
            # Allowed: update config (such as model override)
            if config is not None:
                new_cfg = copy.deepcopy(config)
                spec = SYSTEM_AGENT_SPECS.get(agent.system_key or "", {})
                if spec:
                    new_cfg["name"] = spec["config"]["name"]
                    if "status" in spec["config"]:
                        new_cfg["status"] = spec["config"]["status"]
                agent.config = new_cfg
        else:
            if name is not None:
                if name in {s["name"] for s in SYSTEM_AGENT_SPECS.values()}:
                    raise ValueError(f"Agent name '{name}' is reserved for built-in system agents")
                agent.name = name
            if config is not None:
                agent.config = config
        await session.commit()
        await session.refresh(agent)
        return agent
