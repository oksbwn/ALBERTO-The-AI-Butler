"""ChannelService - CRUD for communication channels + explicit, deterministic routing config.

A Channel is a communication connection (email, Telegram). It is independent of Workflows:
new channels default to the Master Agent, and a Workflow / Subagent destination is an explicit,
optional choice. Inbound events look the channel up by its public `key`; the ChannelGateway
(services/channel_gateway.py) verifies identity and routes. There is deliberately NO implicit
"first active workflow" fallback.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from alberto.models import Agent, Channel, Workflow

CHANNEL_TYPES = ("email", "telegram")
TARGET_TYPES = ("master_agent", "subagent", "workflow")


class RoutingConfigError(ValueError):
    pass


def normalize_command(cmd: str) -> str:
    cmd = (cmd or "").strip().lower()
    if not cmd.startswith("/") or len(cmd) < 2 or any(c.isspace() for c in cmd):
        raise RoutingConfigError(f"route command {cmd!r} must look like '/status' (no spaces)")
    return cmd.split("@", 1)[0]


class ChannelService:
    @staticmethod
    async def list(session, tenant_id: str, project_id: str) -> list[Channel]:
        rows = await session.execute(
            select(Channel).where(Channel.tenant_id == tenant_id, Channel.project_id == project_id)
        )
        return list(rows.scalars())

    @staticmethod
    async def get(session, tenant_id: str, channel_id: str) -> Channel | None:
        return (await session.execute(
            select(Channel).where(Channel.tenant_id == tenant_id, Channel.id == channel_id)
        )).scalar_one_or_none()

    @staticmethod
    async def by_key(session, type_: str, key: str) -> Channel | None:
        return (await session.execute(
            select(Channel).where(Channel.type == type_, Channel.key == key, Channel.enabled.is_(True))
        )).scalar_one_or_none()

    @staticmethod
    async def validate_target(session, tenant_id: str, project_id: str, target_type: str,
                              target_id: str | None) -> None:
        """Raise RoutingConfigError unless the destination is valid and in scope."""
        if target_type not in TARGET_TYPES:
            raise RoutingConfigError(f"unknown target_type {target_type!r}")
        if target_type == "master_agent":
            return
        if not target_id:
            raise RoutingConfigError(f"target_type {target_type!r} requires a target_id")
        if target_type == "workflow":
            wf = (await session.execute(select(Workflow).where(
                Workflow.id == target_id, Workflow.tenant_id == tenant_id, Workflow.project_id == project_id,
            ))).scalar_one_or_none()
            if wf is None:
                raise RoutingConfigError("workflow not found in this project")
        else:
            ag = (await session.execute(select(Agent).where(
                Agent.id == target_id, Agent.tenant_id == tenant_id, Agent.project_id == project_id,
            ))).scalar_one_or_none()
            if ag is None:
                raise RoutingConfigError("subagent not found in this project")
            if ag.system_key in ("tool_manager", "graph_manager", "memory_curator"):
                raise RoutingConfigError(
                    f"the {ag.name} ({ag.system_key}) is an internal management subagent and cannot be a conversational destination"
                )

    @staticmethod
    async def validate_routes(session, tenant_id: str, project_id: str, routes: Any) -> Any:
        out: list[dict] = []
        seen: set[str] = set()
        for r in routes or []:
            if not isinstance(r, dict):
                raise RoutingConfigError("each route must be an object")
            cmd = normalize_command(r.get("command", ""))
            if cmd in seen:
                raise RoutingConfigError(f"duplicate route for {cmd}")
            seen.add(cmd)
            tt = r.get("target_type")
            if not tt or not isinstance(tt, str):
                raise RoutingConfigError("each route must specify a target_type string")
            await ChannelService.validate_target(session, tenant_id, project_id, tt, r.get("target_id"))
            out.append({"command": cmd, "target_type": tt, "target_id": r.get("target_id")})
        return out

    @staticmethod
    async def create(session, tenant_id: str, project_id: str, *, type_: str, name: str,
                     workflow_id: str | None = None, config: dict | None = None,
                     target_type: str | None = None, target_id: str | None = None,
                     routes: Any = None) -> Channel:
        if type_ not in CHANNEL_TYPES:
            raise ValueError(f"unknown channel type {type_!r}")
        # Back-compat: a bare workflow_id (old clients) means an explicit workflow destination.
        if target_type is None:
            target_type, target_id = ("workflow", workflow_id) if workflow_id else ("master_agent", None)
        await ChannelService.validate_target(session, tenant_id, project_id, target_type, target_id)
        clean_routes = await ChannelService.validate_routes(session, tenant_id, project_id, routes)
        ch = Channel(
            tenant_id=tenant_id, project_id=project_id, type=type_, name=name,
            workflow_id=target_id if target_type == "workflow" else None,
            target_type=target_type, target_id=target_id if target_type != "master_agent" else None,
            routing_state="ok", routes=clean_routes, state={},
            config=config or {}, key=uuid.uuid4().hex, enabled=True,
        )
        session.add(ch)
        await session.commit()
        await session.refresh(ch)
        return ch

    @staticmethod
    async def update(session, ch: Channel, *, name=None, workflow_id=None, config=None, enabled=None) -> Channel:
        if name is not None:
            ch.name = name
        if workflow_id is not None:
            # Legacy PATCH field: an explicit workflow destination (also confirms a needs_review channel).
            await ChannelService.validate_target(session, ch.tenant_id, ch.project_id, "workflow", workflow_id)
            ch.workflow_id = workflow_id
            ch.target_type, ch.target_id, ch.routing_state = "workflow", workflow_id, "ok"
        if config is not None:
            ch.config = config
        if enabled is not None:
            ch.enabled = enabled
        await session.commit()
        await session.refresh(ch)
        return ch

    @staticmethod
    async def set_routing(session, ch: Channel, *, target_type: str | None = None, target_id: str | None = None,
                          routes: Any = None, confirm: bool = True) -> Channel:
        """Explicitly (re)configure destination and/or command routes. Confirming a destination
        clears a legacy `needs_review` flag."""
        if target_type is not None:
            await ChannelService.validate_target(session, ch.tenant_id, ch.project_id, target_type, target_id)
            ch.target_type = target_type
            ch.target_id = target_id if target_type != "master_agent" else None
            ch.workflow_id = target_id if target_type == "workflow" else None
            if confirm:
                ch.routing_state = "ok"
        if routes is not None:
            ch.routes = await ChannelService.validate_routes(session, ch.tenant_id, ch.project_id, routes)
        await session.commit()
        await session.refresh(ch)
        return ch

    @staticmethod
    async def delete(session, ch: Channel) -> None:
        await session.delete(ch)
        await session.commit()

    @staticmethod
    async def resolve_workflow_id(session, ch: Channel) -> str | None:
        """The workflow explicitly bound to this channel (or None).

        Integrations v3: the old fallback to "the project's first active workflow" was removed -
        it could run an unrelated workflow on arbitrary inbound traffic."""
        if ch.target_type == "workflow":
            return ch.target_id or ch.workflow_id
        if ch.target_type is None and ch.routing_state != "needs_review":
            return ch.workflow_id
        return None
