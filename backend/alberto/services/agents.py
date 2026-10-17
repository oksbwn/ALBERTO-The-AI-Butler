"""Agent preset CRUD. Config validates against the agent node schema (forge/nodes/agent)."""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.models import Agent
from alberto.schemas.contracts import validate_against_id

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
}

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
        return list(all_agents.scalars())

    @staticmethod
    async def list(session: AsyncSession, tenant_id: str, project_id: str) -> list[Agent]:
        await AgentService.ensure_system_agents(session, tenant_id, project_id)
        rows = await session.execute(
            select(Agent)
            .where(Agent.tenant_id == tenant_id, Agent.project_id == project_id)
            .order_by(Agent.is_system.asc(), Agent.created_at.asc())
        )
        return list(rows.scalars())

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
