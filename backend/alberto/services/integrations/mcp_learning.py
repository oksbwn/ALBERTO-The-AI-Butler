"""MCP Execution Learning Service.

Opportunistically learns durable facts, entities, and relationships from
successful, authorised MCP tool executions without background polling.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.db import SessionLocal
from alberto.models import McpClient, MemoryLearningEvent, Project
from alberto.schemas.memory_curator import (
    EntityCandidate,
    MemoryCandidate,
    MemoryCuratorOutput,
    RelationshipCandidate,
)
from alberto.services.graph_manager import GraphManagerService
from alberto.services.memory_curator import SENSITIVE_PATTERNS, MemoryCuratorService
from alberto.services.unified_memory import UnifiedMemoryManager
from alberto.tools.mcp import McpExecutionOutcome

logger = logging.getLogger("alberto.services.mcp_learning")


class McpLearningService:
    """Orchestrates learning from authorised MCP tool execution results."""

    _active_tasks: set[asyncio.Task] = set()

    @classmethod
    async def is_tool_learning_enabled(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        client_id: str | None = None,
    ) -> bool:
        """Verify that BOTH project-level tool learning AND integration-level learning are enabled."""
        proj = (
            await session.execute(
                select(Project).where(
                    Project.tenant_id == tenant_id,
                    Project.id == project_id,
                )
            )
        ).scalar_one_or_none()

        # Project config must explicitly enable tool execution learning (default False)
        project_enabled = False
        if proj and proj.config:
            project_enabled = bool(proj.config.get("tool_execution_learning_enabled", False))

        if not project_enabled:
            return False

        # If a client_id is given, check that the specific integration permits learning
        if client_id:
            client = (
                await session.execute(
                    select(McpClient).where(
                        McpClient.tenant_id == tenant_id,
                        McpClient.id == client_id,
                    )
                )
            ).scalar_one_or_none()
            if not client or not getattr(client, "enabled", True) or not client.learning_enabled:
                return False

        return True

    @classmethod
    def is_eligible_execution(
        cls,
        tool_name: str,
        tool_input: Any,
        tool_output: Any,
        execution_outcome: McpExecutionOutcome | str | None = None,
    ) -> tuple[bool, str]:
        """Check if a tool execution result is eligible for durable knowledge extraction."""
        if tool_output is None:
            return False, "Tool output is None"

        out_str = json.dumps(tool_output) if isinstance(tool_output, (dict, list)) else str(tool_output)
        out_str = out_str.strip()
        lower_out = out_str.lower()

        if len(out_str) < 5:
            return False, "Tool output too short"

        # 1. Authoritative Execution Outcome Check
        if execution_outcome is not None:
            if execution_outcome == McpExecutionOutcome.UNKNOWN or str(execution_outcome).upper() == "UNKNOWN":
                return False, "Tool execution status is unknown or untrusted"
            if execution_outcome in (McpExecutionOutcome.PERMISSION_DENIED, "PERMISSION_DENIED"):
                return False, "Tool execution was denied by tenant or entitlement permissions"
            if execution_outcome in (McpExecutionOutcome.APPROVAL_REJECTED, "APPROVAL_REJECTED"):
                return False, "Tool execution was rejected or unapproved by HITL"
            if execution_outcome in (McpExecutionOutcome.TOOL_ERROR, "TOOL_ERROR"):
                return False, "Tool execution failed with error"
            if execution_outcome in (McpExecutionOutcome.TIMEOUT, "TIMEOUT"):
                return False, "Tool execution timed out"
            if execution_outcome in (McpExecutionOutcome.CANCELLED, "CANCELLED"):
                return False, "Tool execution was cancelled"
            if execution_outcome not in (McpExecutionOutcome.SUCCESS, "SUCCESS"):
                return False, f"Tool execution outcome not eligible: {execution_outcome}"

        # 2. Structured MCP protocol error check (always applies)
        if isinstance(tool_output, dict):
            if tool_output.get("isError") or tool_output.get("is_error") or "error" in tool_output:
                return False, "Tool returned error"
            if str(tool_output.get("decision", "")).lower() == "reject":
                return False, "Tool execution was rejected"
            if str(tool_output.get("status", "")).lower() in ("denied", "rejected", "error"):
                return False, "Tool execution was not authorized"

        # 3. Secondary Safeguard for legacy unstructured callers where outcome was omitted
        if execution_outcome is None:
            if (
                lower_out.startswith("error:")
                or lower_out.startswith("not permitted")
                or lower_out.startswith("permission denied")
                or lower_out.startswith("access denied")
                or lower_out.startswith("unauthorized")
                or lower_out.startswith("[human decision] reject")
                or lower_out == "reject"
                or "unhandled error" in lower_out
                or "not permitted" in lower_out
                or "access denied" in lower_out
            ):
                return False, "Tool returned error or permission denial"

        # Check for sensitive patterns
        for pattern in SENSITIVE_PATTERNS:
            if re.search(pattern, out_str):
                return False, "Tool output contains sensitive credentials"

        # Check for instruction injection attempts in external tool data
        if (
            "ignore previous instructions" in lower_out
            or "ignore all previous" in lower_out
            or "system prompt" in lower_out
            or "you are now" in lower_out
        ):
            return False, "Potential instruction injection in tool output"

        return True, "Eligible"

    @classmethod
    def parse_structured_output(
        cls,
        tool_name: str,
        tool_output: Any,
        source_ref: str,
    ) -> MemoryCuratorOutput:
        """Deterministic-first extraction for structured tool outputs (e.g. device inventory)."""
        memories: list[MemoryCandidate] = []
        entities: list[EntityCandidate] = []
        relationships: list[RelationshipCandidate] = []

        now_iso = datetime.now(UTC).isoformat()

        # Handle list of items or single dict
        items: list[dict[str, Any]] = []
        if isinstance(tool_output, list):
            items = [x for x in tool_output if isinstance(x, dict)]
        elif isinstance(tool_output, dict):
            # Check for container keys like 'devices', 'results', 'data'
            for key in ("devices", "entities", "results", "items", "data"):
                if isinstance(tool_output.get(key), list):
                    items = [x for x in tool_output[key] if isinstance(x, dict)]
                    break
            if not items:
                items = [tool_output]

        for idx, item in enumerate(items):
            name = item.get("name") or item.get("id") or item.get("title") or item.get("entity_id")
            if not name or not isinstance(name, str):
                continue

            clean_name = name.strip()
            kind = str(item.get("kind") or item.get("type") or item.get("domain") or "device").lower()
            model = item.get("model") or item.get("manufacturer") or item.get("brand")
            room = item.get("room") or item.get("area") or item.get("location")
            state = item.get("state") or item.get("status")

            # 1. Durable Entity
            desc_parts = []
            if model:
                desc_parts.append(f"Model: {model}")
            if room:
                desc_parts.append(f"Location: {room}")
            desc = ", ".join(desc_parts) if desc_parts else f"Discovered via {tool_name}"

            ent_id = f"ent_{idx}"
            entities.append(
                EntityCandidate(
                    temporary_id=ent_id,
                    name=clean_name,
                    kind=kind,
                    confidence=1.0,
                    description=desc,
                    evidence_refs=[clean_name],
                )
            )

            # 2. Durable Fact
            fact_text = f"Device {clean_name} ({kind}) discovered"
            if desc_parts:
                fact_text += f" with {desc}"
            memories.append(
                MemoryCandidate(
                    kind="device",
                    content=fact_text,
                    confidence=1.0,
                    durability="long_term",
                    evidence_refs=[clean_name],
                    operation="propose_upsert",
                )
            )

            # 3. Ephemeral / Timestamped observation for temporary state
            if state is not None:
                state_fact = f"{clean_name} observed state '{state}' at {now_iso}"
                memories.append(
                    MemoryCandidate(
                        kind="observation",
                        content=state_fact,
                        confidence=0.9,
                        durability="ephemeral",
                        evidence_refs=[clean_name],
                        operation="propose_upsert",
                    )
                )

            # 4. Location relationship if room is present
            if room and isinstance(room, str):
                room_ent_id = f"room_{idx}"
                entities.append(
                    EntityCandidate(
                        temporary_id=room_ent_id,
                        name=room.strip(),
                        kind="location",
                        confidence=1.0,
                        description=f"Location for {clean_name}",
                        evidence_refs=[room],
                    )
                )
                relationships.append(
                    RelationshipCandidate(
                        source_ref=ent_id,
                        target_ref=room_ent_id,
                        kind="LOCATED_IN",
                        confidence=1.0,
                        evidence_refs=[clean_name, room],
                    )
                )

        should_learn = len(memories) > 0 or len(entities) > 0
        return MemoryCuratorOutput(
            schema_version=1,
            should_learn=should_learn,
            memories=memories,
            entities=entities,
            relationships=relationships,
            conflicts=[],
            requires_review=False,
        )

    @classmethod
    async def schedule_tool_learning(
        cls,
        tenant_id: str,
        project_id: str,
        client_id: str,
        client_name: str,
        tool_name: str,
        tool_input: Any,
        tool_output: Any,
        execution_id: str | None = None,
        execution_outcome: McpExecutionOutcome | str = McpExecutionOutcome.UNKNOWN,
    ) -> MemoryLearningEvent | None:
        """Check eligibility and durably persist learning event before processing."""
        # Fail closed on any non-SUCCESS outcome
        if execution_outcome != McpExecutionOutcome.SUCCESS and execution_outcome != "SUCCESS":
            logger.debug("Tool execution not eligible for learning: execution outcome is %s", execution_outcome)
            return None

        eligible, reason = cls.is_eligible_execution(
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            execution_outcome=execution_outcome,
        )
        if not eligible:
            logger.debug("Tool execution not eligible for learning: %s", reason)
            return None

        exec_id = execution_id or str(uuid.uuid4())[:12]
        source_event_id = f"mcp:{client_id}:{tool_name}:{exec_id}"

        async with SessionLocal() as session:
            if not await cls.is_tool_learning_enabled(session, tenant_id, project_id, client_id):
                return None

            existing = (
                await session.execute(
                    select(MemoryLearningEvent).where(
                        MemoryLearningEvent.tenant_id == tenant_id,
                        MemoryLearningEvent.project_id == project_id,
                        MemoryLearningEvent.source_event_id == source_event_id,
                    )
                )
            ).scalar_one_or_none()

            if existing:
                if existing.status in ("completed", "review_required", "rejected"):
                    return existing
                event = existing
            else:
                event = MemoryLearningEvent(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    source_event_id=source_event_id,
                    source_type="mcp_tool",
                    status="pending",
                    extraction_payload={
                        "tool_execution": {
                            "integration_id": client_id,
                            "integration_name": client_name,
                            "tool_name": tool_name,
                            "tool_input": tool_input,
                            "tool_output": tool_output,
                            "execution_id": exec_id,
                            "execution_outcome": execution_outcome.value if isinstance(execution_outcome, McpExecutionOutcome) else execution_outcome,
                            "timestamp": datetime.now(UTC).isoformat(),
                        }
                    },
                    applied_memory_ids=[],
                    applied_graph_entity_ids=[],
                    applied_graph_rel_ids=[],
                )
                session.add(event)
                await session.commit()
                await session.refresh(event)

        task = asyncio.create_task(
            cls.process_tool_learning(
                tenant_id=tenant_id,
                project_id=project_id,
                source_event_id=source_event_id,
            )
        )
        cls._active_tasks.add(task)
        task.add_done_callback(cls._active_tasks.discard)
        return event

    @classmethod
    async def process_tool_learning(
        cls,
        tenant_id: str,
        project_id: str,
        source_event_id: str,
        override_enabled_check: bool = False,
    ) -> MemoryLearningEvent | None:
        """Process MCP tool execution learning with validation and cross-store application."""
        async with SessionLocal() as session:
            event = (
                await session.execute(
                    select(MemoryLearningEvent).where(
                        MemoryLearningEvent.tenant_id == tenant_id,
                        MemoryLearningEvent.project_id == project_id,
                        MemoryLearningEvent.source_event_id == source_event_id,
                    )
                )
            ).scalar_one_or_none()

            if not event:
                return None

            if event.status in ("completed", "review_required", "rejected"):
                return event

            tool_data = (event.extraction_payload or {}).get("tool_execution", {})
            exec_outcome = tool_data.get("execution_outcome", McpExecutionOutcome.SUCCESS.value)
            if exec_outcome != McpExecutionOutcome.SUCCESS.value and exec_outcome != "SUCCESS":
                event.status = "rejected"
                event.error = f"Execution outcome is not successful: {exec_outcome}"
                await session.commit()
                return event

            client_id = (event.extraction_payload or {}).get("tool_execution", {}).get("integration_id")
            if not override_enabled_check and not await cls.is_tool_learning_enabled(session, tenant_id, project_id, client_id):
                event.status = "cancelled"
                event.error = "Tool learning disabled"
                await session.commit()
                return event

            tool_name = tool_data.get("tool_name", "unknown")
            tool_output = tool_data.get("tool_output")

            # 1. Extraction: Parse structured data deterministically
            if isinstance(tool_output, (dict, list)):
                curator_output = cls.parse_structured_output(tool_name, tool_output, source_event_id)
            else:
                # Fallback to single MemoryCurator pass if raw prose
                curator_output = await MemoryCuratorService.extract(
                    session=session,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    user_message=f"MCP Tool {tool_name} returned observation",
                    ai_response=str(tool_output),
                )

            event.extraction_payload = {
                **(event.extraction_payload or {}),
                "curator_output": curator_output.model_dump(),
            }

            if not curator_output.should_learn or not curator_output.memories:
                event.status = "completed"
                await session.commit()
                return event

            # 2. Validation: deterministic graph entity & relationship resolution (read-only)
            resolution = await GraphManagerService.resolve_and_validate(
                tenant_id=tenant_id,
                project_id=project_id,
                candidate_entities=curator_output.entities,
                candidate_relationships=curator_output.relationships,
                source_ref=source_event_id,
            )

            requires_review = curator_output.requires_review or resolution["requires_review"]
            if requires_review:
                event.status = "review_required"
                event.requires_review = True
                await session.commit()
                return event

            # 3. Application: persist to LadybugDB, SQLite, and Markdown
            event.status = "applying"
            await session.commit()

            # LadybugDB mutations
            applied_graph = await GraphManagerService.apply_resolved(
                tenant_id=tenant_id,
                project_id=project_id,
                resolved_entities=resolution["resolved_entities"],
                resolved_relationships=resolution["resolved_relationships"],
            )
            event.applied_graph_entity_ids = applied_graph["applied_entities"]
            event.applied_graph_rel_ids = applied_graph["applied_relationships"]

            # SQLite + Chroma + Markdown memory records
            applied_mem_ids: list[str] = []
            for mem_cand in curator_output.memories:
                res = await UnifiedMemoryManager.remember(
                    session=session,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    text=mem_cand.content,
                    target="memory",
                    scope="default",
                    kind=mem_cand.kind,
                    confidence=mem_cand.confidence or 1.0,
                    provenance=f"mcp_tool:{tool_name}",
                    status="active",
                )
                if res and "id" in res:
                    applied_mem_ids.append(res["id"])

            event.applied_memory_ids = applied_mem_ids
            event.status = "completed"
            await session.commit()
            await session.refresh(event)
            return event
