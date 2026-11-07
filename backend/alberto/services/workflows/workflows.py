"""Workflow CRUD + validation. (Canvas->executable translation lands in Phase 4.)"""

from __future__ import annotations

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.models import Run, Span, Thread, Trace, Trigger, Workflow
from alberto.services.validation import ValidationResult, validate_workflow


class WorkflowService:
    @staticmethod
    async def list(session: AsyncSession, tenant_id: str, project_id: str) -> list[Workflow]:
        rows = await session.execute(
            select(Workflow).where(
                Workflow.tenant_id == tenant_id, Workflow.project_id == project_id
            )
        )
        return list(rows.scalars())

    @staticmethod
    async def get(session: AsyncSession, tenant_id: str, workflow_id: str) -> Workflow | None:
        row = await session.execute(
            select(Workflow).where(Workflow.tenant_id == tenant_id, Workflow.id == workflow_id)
        )
        return row.scalar_one_or_none()

    @staticmethod
    async def create(
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        *,
        name: str,
        description: str | None = None,
        executable: dict | None = None,
        canvas: dict | None = None,
    ) -> Workflow:
        wf = Workflow(
            tenant_id=tenant_id,
            project_id=project_id,
            name=name,
            description=description,
            executable=executable or {},
            canvas=canvas or {},
        )
        session.add(wf)
        await session.commit()
        await session.refresh(wf)
        if wf.executable:
            await WorkflowService._sync_triggers(session, wf)
            await WorkflowService._sync_knowledge_graph(session, wf)
        return wf

    @staticmethod
    async def delete(session: AsyncSession, wf: Workflow) -> None:
        """Delete a workflow and its execution history (threads, runs, traces, spans).

        Runs/threads/traces reference workflow_id by value (no hard FK), so we clean
        them up explicitly to avoid orphan rows polluting the dashboard and Traces.
        """
        trace_ids = (
            await session.execute(select(Trace.id).where(Trace.workflow_id == wf.id))
        ).scalars().all()
        if trace_ids:
            await session.execute(sa_delete(Span).where(Span.trace_id.in_(trace_ids)))
        await session.execute(sa_delete(Trace).where(Trace.workflow_id == wf.id))
        await session.execute(sa_delete(Run).where(Run.workflow_id == wf.id))
        await session.execute(sa_delete(Thread).where(Thread.workflow_id == wf.id))
        await session.execute(sa_delete(Trigger).where(Trigger.workflow_id == wf.id))
        await session.delete(wf)
        await session.commit()

        # Clean up entity in LadybugDB Knowledge Graph (best-effort)
        try:
            from alberto.knowledge.graph import get_graph_adapter, make_entity_id
            adapter = get_graph_adapter()
            wf_entity_id = make_entity_id(wf.tenant_id, wf.project_id, "workflow", wf.name)
            await adapter.delete_entity(wf.tenant_id, wf.project_id, wf_entity_id)
        except Exception:
            pass

    @staticmethod
    async def update(
        session: AsyncSession,
        wf: Workflow,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> Workflow:
        if name is not None:
            wf.name = name
        if description is not None:
            wf.description = description
        await session.commit()
        await session.refresh(wf)
        await WorkflowService._sync_knowledge_graph(session, wf)
        return wf

    @staticmethod
    def validate(executable: dict) -> ValidationResult:
        return validate_workflow(executable)

    @staticmethod
    async def update_executable(
        session: AsyncSession, wf: Workflow, executable: dict, *, require_valid: bool = True,
        owner: str | None = None, scope: str | None = None,
    ) -> ValidationResult:
        result = validate_workflow(executable)
        if result.valid or not require_valid:
            wf.executable = executable
            await session.commit()
            await session.refresh(wf)
            await WorkflowService._sync_triggers(session, wf, owner=owner, scope=scope)
            await WorkflowService._sync_knowledge_graph(session, wf)
        return result

    @staticmethod
    async def save_canvas(
        session: AsyncSession, wf: Workflow, canvas: dict, executable: dict,
        *, owner: str | None = None, scope: str | None = None,
    ) -> ValidationResult:
        """Persist the canvas (UI-owned) + compiled executable, and validate.

        Both are stored regardless of validity so the builder round-trips WIP work;
        the returned result lets the UI surface problems and gate Run/Publish.
        """
        result = validate_workflow(executable)
        wf.canvas = canvas
        wf.executable = executable
        wf.active_version = (wf.active_version or 1) + 1
        await session.commit()
        await session.refresh(wf)
        await WorkflowService._sync_triggers(session, wf, owner=owner, scope=scope)
        await WorkflowService._sync_knowledge_graph(session, wf)
        return result

    @staticmethod
    async def _sync_triggers(session: AsyncSession, wf: Workflow, *, owner: str | None = None,
                             scope: str | None = None) -> None:
        """Mirror the workflow's trigger nodes into Trigger rows (best-effort).

        `owner` (the editor saving) is stamped on triggers that don't have one yet - it is the
        identity an unattended run acts as, so a scheduled workflow can use the connected
        accounts of the person who built it. `scope` decides whether a NEW trigger belongs to
        the project or to that person. Neither ever overwrites an existing trigger's values.
        """
        try:
            from alberto.services.triggers import TriggerService

            await TriggerService.sync_from_workflow(session, wf, owner=owner, scope=scope)
        except Exception:  # noqa: BLE001 - trigger sync must not block saving a workflow
            pass

    @staticmethod
    async def _sync_knowledge_graph(session: AsyncSession, wf: Workflow) -> None:
        """Mirror workflow and its component associations into LadybugDB Knowledge Graph (best-effort)."""
        try:
            from alberto.knowledge.graph import (
                GraphEntity,
                GraphRelationship,
                get_graph_adapter,
                make_entity_id,
                make_relationship_id,
            )

            adapter = get_graph_adapter()
            exec_data = wf.executable or {}
            nodes = exec_data.get("nodes", [])

            trigger_types = [
                n.get("type", "")
                for n in nodes
                if "trigger" in n.get("type", "").lower() or n.get("type") in ("webhook", "schedule")
            ]
            agent_names = [
                (n.get("config") or {}).get("name") or n.get("id")
                for n in nodes
                if n.get("type") == "agent" and ((n.get("config") or {}).get("name") or n.get("id"))
            ]
            tool_names = [
                (n.get("config") or {}).get("tool_id")
                or (n.get("config") or {}).get("tool")
                or (n.get("config") or {}).get("name")
                for n in nodes
                if n.get("type") in ("tool", "tool_call")
                and (
                    (n.get("config") or {}).get("tool_id")
                    or (n.get("config") or {}).get("tool")
                    or (n.get("config") or {}).get("name")
                )
            ]

            desc_parts = [
                f"Workflow '{wf.name}' [Status: {wf.status}, Version: {wf.active_version or 1}].",
                f"Triggers: {', '.join(trigger_types) or 'manual'}.",
                f"Nodes ({len(nodes)}): {', '.join(str(n.get('type', '')) for n in nodes)}.",
            ]
            if wf.description:
                desc_parts.append(wf.description)

            wf_entity_id = make_entity_id(wf.tenant_id, wf.project_id, "workflow", wf.name)
            wf_entity = GraphEntity(
                id=wf_entity_id,
                tenant_id=wf.tenant_id,
                project_id=wf.project_id,
                kind="workflow",
                name=wf.name,
                canonical_name=wf.name.lower(),
                description=" ".join(desc_parts),
                source="workflow_engine",
                confidence=1.0,
            )
            await adapter.create_or_update_entity(wf_entity)

            # Link agents
            for a_name in set(agent_names):
                if not a_name:
                    continue
                a_id = make_entity_id(wf.tenant_id, wf.project_id, "agent", a_name)
                a_entity = GraphEntity(
                    id=a_id,
                    tenant_id=wf.tenant_id,
                    project_id=wf.project_id,
                    kind="agent",
                    name=a_name,
                    canonical_name=a_name.lower(),
                    description=f"Specialist agent '{a_name}' orchestrated by workflow '{wf.name}'",
                    source="workflow_engine",
                    confidence=1.0,
                )
                await adapter.create_or_update_entity(a_entity)
                rel_id = make_relationship_id(wf.tenant_id, wf.project_id, "USES", wf_entity_id, a_id)
                await adapter.create_or_update_relationship(
                    GraphRelationship(
                        id=rel_id,
                        source_id=wf_entity_id,
                        target_id=a_id,
                        kind="USES",
                        tenant_id=wf.tenant_id,
                        project_id=wf.project_id,
                        source="workflow_engine",
                        confidence=1.0,
                    )
                )

            # Link tools
            for t_name in set(tool_names):
                if not t_name:
                    continue
                t_id = make_entity_id(wf.tenant_id, wf.project_id, "tool", str(t_name))
                t_entity = GraphEntity(
                    id=t_id,
                    tenant_id=wf.tenant_id,
                    project_id=wf.project_id,
                    kind="tool",
                    name=str(t_name),
                    canonical_name=str(t_name).lower(),
                    description=f"Tool '{t_name}' utilized by workflow '{wf.name}'",
                    source="workflow_engine",
                    confidence=1.0,
                )
                await adapter.create_or_update_entity(t_entity)
                rel_id = make_relationship_id(wf.tenant_id, wf.project_id, "USES", wf_entity_id, t_id)
                await adapter.create_or_update_relationship(
                    GraphRelationship(
                        id=rel_id,
                        source_id=wf_entity_id,
                        target_id=t_id,
                        kind="USES",
                        tenant_id=wf.tenant_id,
                        project_id=wf.project_id,
                        source="workflow_engine",
                        confidence=1.0,
                    )
                )
        except Exception:
            # Graph sync is best-effort and must never block or break workflow operations
            pass
