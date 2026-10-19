"""Tests for Milestone 2.0 protected built-in system agents and dynamic model inheritance."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from alberto.db import SessionLocal
from alberto.engine.models import resolve_model
from alberto.models.entities import Agent, Project
from alberto.services.agents import (
    RESERVED_SYSTEM_KEYS,
    SYSTEM_AGENT_SPECS,
    AgentService,
)
from alberto.services.projects import ProjectService


@pytest.fixture
async def sample_project():
    async with SessionLocal() as session:
        proj = await ProjectService.create(
            session,
            tenant_id="tenant-sys-1",
            name="System Agents Project",
            slug="sys-proj-1",
        )
        await session.commit()
        await session.refresh(proj)
        return proj


@pytest.mark.asyncio
async def test_system_agents_provisioning(sample_project: Project):
    async with SessionLocal() as session:
        # Provision system agents
        sys_agents = await AgentService.ensure_system_agents(
            session, sample_project.tenant_id, sample_project.id
        )
        assert len(sys_agents) == 4

        keys = {a.system_key for a in sys_agents}
        assert keys == {"intent_router", "memory_curator", "graph_manager", "tool_manager"}

        for a in sys_agents:
            assert a.is_system is True
            assert a.system_key in RESERVED_SYSTEM_KEYS
            assert a.name == SYSTEM_AGENT_SPECS[a.system_key]["name"]


@pytest.mark.asyncio
async def test_system_agents_idempotency_and_preserve_overrides(sample_project: Project):
    async with SessionLocal() as session:
        await AgentService.ensure_system_agents(
            session, sample_project.tenant_id, sample_project.id
        )

        # Set a custom model override on intent_router
        agent = (
            await session.execute(
                select(Agent).where(
                    Agent.tenant_id == sample_project.tenant_id,
                    Agent.project_id == sample_project.id,
                    Agent.system_key == "intent_router",
                )
            )
        ).scalar_one()

        cfg = dict(agent.config)
        cfg["model"] = "fake:custom_override_reply"
        await AgentService.update(session, agent, config=cfg)

        # Re-run provisioning
        after_reprovision = await AgentService.ensure_system_agents(
            session, sample_project.tenant_id, sample_project.id
        )
        assert len(after_reprovision) == 4

        reloaded = (
            await session.execute(
                select(Agent).where(
                    Agent.tenant_id == sample_project.tenant_id,
                    Agent.project_id == sample_project.id,
                    Agent.system_key == "intent_router",
                )
            )
        ).scalar_one()

        # Custom override preserved
        assert reloaded.config.get("model") == "fake:custom_override_reply"


@pytest.mark.asyncio
async def test_system_agent_protections(sample_project: Project):
    async with SessionLocal() as session:
        await AgentService.ensure_system_agents(
            session, sample_project.tenant_id, sample_project.id
        )
        agent = (
            await session.execute(
                select(Agent).where(
                    Agent.tenant_id == sample_project.tenant_id,
                    Agent.project_id == sample_project.id,
                    Agent.system_key == "intent_router",
                )
            )
        ).scalar_one()

        # 1. Reject deletion
        with pytest.raises(ValueError, match="Protected system agents cannot be deleted"):
            await AgentService.delete(session, agent)

        # 2. Reject rename
        with pytest.raises(ValueError, match="Protected system agents cannot be renamed"):
            await AgentService.update(session, agent, name="Renamed Intent Router")

        # 3. Reject user agent creation with reserved system key
        with pytest.raises(ValueError, match="reserved system key"):
            await AgentService.create(
                session,
                sample_project.tenant_id,
                sample_project.id,
                name="Imposter Agent",
                config={},
                is_system=False,
                system_key="intent_router",
            )

        # 4. Reject user agent creation with reserved system name
        with pytest.raises(ValueError, match="reserved for built-in system agents"):
            await AgentService.create(
                session,
                sample_project.tenant_id,
                sample_project.id,
                name="Memory Curator",
                config={},
                is_system=False,
            )


@pytest.mark.asyncio
async def test_dynamic_model_inheritance(sample_project: Project):
    """Verify dynamic model inheritance and override behavior."""
    class MockCompileContext:
        default_model = "fake:global_default"
        registered_models = {}
        model_servers = {}
        provider_credentials = {}

    ctx = MockCompileContext()

    # 1. No override -> inherits global default model
    model = resolve_model(None, ctx=ctx)
    res = model.invoke("test")
    assert "global_default" in res.content

    # 2. Explicit model override
    model_override = resolve_model("fake:overridden_model", ctx=ctx)
    res2 = model_override.invoke("test")
    assert "overridden_model" in res2.content

    # 3. Dynamic change of global default
    ctx.default_model = "fake:updated_global_default"
    model3 = resolve_model(None, ctx=ctx)
    res3 = model3.invoke("test")
    assert "updated_global_default" in res3.content


@pytest.mark.asyncio
async def test_system_agent_inactive_status(sample_project: Project):
    """Verify memory_curator and graph_manager remain inactive in Milestone 2.0."""
    async with SessionLocal() as session:
        await AgentService.ensure_system_agents(
            session, sample_project.tenant_id, sample_project.id
        )

        curator = (
            await session.execute(
                select(Agent).where(
                    Agent.tenant_id == sample_project.tenant_id,
                    Agent.project_id == sample_project.id,
                    Agent.system_key == "memory_curator",
                )
            )
        ).scalar_one()

        graph_mgr = (
            await session.execute(
                select(Agent).where(
                    Agent.tenant_id == sample_project.tenant_id,
                    Agent.project_id == sample_project.id,
                    Agent.system_key == "graph_manager",
                )
            )
        ).scalar_one()

        assert curator.config.get("status") == "inactive"
        assert graph_mgr.config.get("status") == "inactive"


@pytest.mark.asyncio
async def test_concurrent_system_agent_provisioning(sample_project: Project):
    """P1 TEST:
    Concurrent provisioning across independent DB sessions must be idempotent
    and race-resilient, guaranteeing exactly 1 built-in agent per system key.
    """
    import asyncio

    async def provision():
        async with SessionLocal() as session:
            return await AgentService.ensure_system_agents(
                session, sample_project.tenant_id, sample_project.id
            )

    # Launch 5 concurrent provisioning sessions
    results = await asyncio.gather(*(provision() for _ in range(5)))
    for res in results:
        assert len(res) == 4

    # Verify database state has exactly 4 system agents
    async with SessionLocal() as session:
        all_agents = (
            await session.execute(
                select(Agent).where(
                    Agent.tenant_id == sample_project.tenant_id,
                    Agent.project_id == sample_project.id,
                    Agent.is_system.is_(True),
                )
            )
        ).scalars().all()
        assert len(all_agents) == 4
        assert {a.system_key for a in all_agents} == {"intent_router", "memory_curator", "graph_manager", "tool_manager"}


@pytest.mark.asyncio
async def test_database_uniqueness_constraint_enforcement(sample_project: Project):
    """P1 TEST:
    Verify DB-level partial unique constraint uq_agents_tenant_project_system_key.
    1. Reject duplicate system_key for is_system=True within same (tenant, project).
    2. Allow multiple ordinary user agents with system_key=None.
    """
    from sqlalchemy.exc import IntegrityError

    async with SessionLocal() as session:
        # Pre-provision
        await AgentService.ensure_system_agents(
            session, sample_project.tenant_id, sample_project.id
        )

        # 1. Attempt manual duplicate insert with same (tenant, project, system_key)
        duplicate_sys = Agent(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            name="Duplicate Intent Router",
            is_system=True,
            system_key="intent_router",
            config={},
        )
        session.add(duplicate_sys)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        # 2. Ordinary user agents with system_key=None must NOT be constrained
        u1 = Agent(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            name="User Agent 1",
            is_system=False,
            system_key=None,
            config={},
        )
        u2 = Agent(
            tenant_id=sample_project.tenant_id,
            project_id=sample_project.id,
            name="User Agent 2",
            is_system=False,
            system_key=None,
            config={},
        )
        session.add(u1)
        session.add(u2)
        await session.commit()
        await session.refresh(u1)
        await session.refresh(u2)
        assert u1.id != u2.id

