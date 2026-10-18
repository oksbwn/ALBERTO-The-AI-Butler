"""Learning Coordinator: Durable, observable, and bounded conversation learning execution.

Coordinates:
- Durable SQLite event persistence BEFORE background dispatch
- Restart recovery sweep for interrupted turns
- Deterministic candidate validation (evidence, confidence, ambiguity, sensitivity)
- Strict acceptance policy: NO mutations to graph or memory before full approval
- Coordinated storage updates across SQLite, ChromaDB, LadybugDB, and Markdown
- Idempotency and bounded retry / dead-letter handling
- Lifecycle tracking: pending -> extracted -> validated -> applying -> completed / review_required / failed / rejected
"""

from __future__ import annotations

import asyncio
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.config import settings
from alberto.db import SessionLocal
from alberto.models import MemoryLearningEvent
from alberto.schemas.memory_curator import (
    EntityCandidate,
    MemoryCuratorOutput,
    RelationshipCandidate,
)
from alberto.services.audit import AuditService
from alberto.services.graph_manager import GraphManagerService
from alberto.services.markdown_memory import MarkdownMemoryService
from alberto.services.memory import MemoryService
from alberto.services.memory_curator import SENSITIVE_PATTERNS, MemoryCuratorService

logger = logging.getLogger("alberto.services.learning_coordinator")


class LearningCoordinator:
    """Orchestrates durable learning lifecycle from completed conversation turns."""

    _active_tasks: set[asyncio.Task] = set()

    @classmethod
    async def is_learning_enabled(
        cls, session: AsyncSession, tenant_id: str, project_id: str
    ) -> bool:
        """Inspect persisted Project config or fallback to global default."""
        from alberto.models import Project

        proj = (
            await session.execute(
                select(Project).where(
                    Project.tenant_id == tenant_id,
                    Project.id == project_id,
                )
            )
        ).scalar_one_or_none()

        if proj and proj.config and "memory_learning_enabled" in proj.config:
            return bool(proj.config["memory_learning_enabled"])
        return getattr(settings, "memory_learning_enabled", False)

    @classmethod
    async def schedule_turn_learning(
        cls,
        tenant_id: str,
        project_id: str,
        source_event_id: str,
        user_message: str,
        ai_response: str,
    ) -> MemoryLearningEvent | None:
        """Durable non-blocking dispatch of conversation turn learning.
        Persists the event in SQLite before dispatching background processing."""
        eligible, _ = MemoryCuratorService.is_eligible_turn(user_message, ai_response)
        if not eligible:
            return None

        # 1. Synchronously persist or locate the durable learning event row in SQLite
        async with SessionLocal() as session:
            if not await cls.is_learning_enabled(session, tenant_id, project_id):
                return None

            existing_event = (
                await session.execute(
                    select(MemoryLearningEvent).where(
                        MemoryLearningEvent.tenant_id == tenant_id,
                        MemoryLearningEvent.project_id == project_id,
                        MemoryLearningEvent.source_event_id == source_event_id,
                    )
                )
            ).scalar_one_or_none()

            if existing_event:
                if existing_event.status in ("completed", "review_required", "rejected"):
                    return existing_event
                event = existing_event
            else:
                event = MemoryLearningEvent(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    source_event_id=source_event_id,
                    source_type="conversation_turn",
                    status="pending",
                    extraction_payload={"turn": {"user_message": user_message, "ai_response": ai_response}},
                    applied_memory_ids=[],
                    applied_graph_entity_ids=[],
                    applied_graph_rel_ids=[],
                )
                session.add(event)
                await session.commit()
                await session.refresh(event)

        # 2. Dispatch managed in-process background worker
        task = asyncio.create_task(
            cls._safe_run_turn_learning(
                tenant_id, project_id, source_event_id, user_message, ai_response
            )
        )
        cls._active_tasks.add(task)
        task.add_done_callback(cls._active_tasks.discard)
        return event

    @classmethod
    async def _safe_run_turn_learning(
        cls,
        tenant_id: str,
        project_id: str,
        source_event_id: str,
        user_message: str,
        ai_response: str,
    ) -> None:
        timeout = getattr(settings, "memory_learning_timeout_seconds", 30.0)
        try:
            async with asyncio.timeout(timeout):
                async with SessionLocal() as session:
                    await cls.process_learning_turn(
                        session=session,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        source_event_id=source_event_id,
                        user_message=user_message,
                        ai_response=ai_response,
                    )
        except TimeoutError:
            logger.warning("Turn learning timed out for event %s", source_event_id)
            async with SessionLocal() as session:
                ev = (
                    await session.execute(
                        select(MemoryLearningEvent).where(
                            MemoryLearningEvent.tenant_id == tenant_id,
                            MemoryLearningEvent.project_id == project_id,
                            MemoryLearningEvent.source_event_id == source_event_id,
                        )
                    )
                ).scalar_one_or_none()
                if ev and ev.status not in ("completed", "review_required"):
                    ev.status = "failed"
                    ev.error = "Turn learning execution timed out"
                    ev.retry_count += 1
                    await session.commit()
        except Exception as e:
            logger.exception("Turn learning failed for event %s: %s", source_event_id, e)
            async with SessionLocal() as session:
                ev = (
                    await session.execute(
                        select(MemoryLearningEvent).where(
                            MemoryLearningEvent.tenant_id == tenant_id,
                            MemoryLearningEvent.project_id == project_id,
                            MemoryLearningEvent.source_event_id == source_event_id,
                        )
                    )
                ).scalar_one_or_none()
                if ev and ev.status not in ("completed", "review_required"):
                    ev.status = "failed"
                    ev.error = str(e)[:200]
                    ev.retry_count += 1
                    await session.commit()

    @classmethod
    async def process_learning_turn(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        source_event_id: str,
        user_message: str,
        ai_response: str,
        override_enabled_check: bool = False,
    ) -> MemoryLearningEvent | None:
        """Process turn learning with idempotency, coordination, and state transitions."""
        if not override_enabled_check and not await cls.is_learning_enabled(session, tenant_id, project_id):
            existing = (
                await session.execute(
                    select(MemoryLearningEvent).where(
                        MemoryLearningEvent.tenant_id == tenant_id,
                        MemoryLearningEvent.project_id == project_id,
                        MemoryLearningEvent.source_event_id == source_event_id,
                    )
                )
            ).scalar_one_or_none()
            if existing and existing.status in ("pending", "applying"):
                existing.status = "cancelled"
                existing.error = "Learning scope disabled for project"
                await session.commit()
            return None

        # 1. Locate or create event
        existing_event = (
            await session.execute(
                select(MemoryLearningEvent).where(
                    MemoryLearningEvent.tenant_id == tenant_id,
                    MemoryLearningEvent.project_id == project_id,
                    MemoryLearningEvent.source_event_id == source_event_id,
                )
            )
        ).scalar_one_or_none()

        if existing_event:
            if existing_event.status in ("completed", "review_required", "rejected"):
                return existing_event
            event = existing_event
        else:
            event = MemoryLearningEvent(
                tenant_id=tenant_id,
                project_id=project_id,
                source_event_id=source_event_id,
                source_type="conversation_turn",
                status="pending",
                extraction_payload={"turn": {"user_message": user_message, "ai_response": ai_response}},
                applied_memory_ids=[],
                applied_graph_entity_ids=[],
                applied_graph_rel_ids=[],
            )
            session.add(event)
            await session.commit()
            await session.refresh(event)

        # Check bounded retry policy
        max_retries = getattr(settings, "memory_learning_max_retries", 3)
        if event.retry_count >= max_retries:
            event.status = "failed"
            event.error = f"Exceeded maximum retry attempts ({max_retries}) (dead-lettered)"
            await session.commit()
            return event

        try:
            # 2. Extract durable candidates (or reuse saved extraction if retrying after extraction)
            payload = dict(event.extraction_payload or {})
            saved_output = payload.get("curator_output")
            if event.status == "extracted" and saved_output:
                logger.info("Reusing saved extraction payload for event %s on retry", source_event_id)
                curator_output = MemoryCuratorOutput.model_validate(saved_output)
            else:
                event.status = "extracted"
                existing_active_mems = await MemoryService.list(session, tenant_id, project_id, status="active")
                mem_texts = [m.text for m in existing_active_mems]
                await session.commit()

                curator_output = await MemoryCuratorService.extract(
                    session=session,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    user_message=user_message,
                    ai_response=ai_response,
                    existing_memories=mem_texts,
                )

                if curator_output.extraction_error:
                    event.status = "failed"
                    err_str = curator_output.extraction_error
                    event.error = err_str
                    event.retry_count += 1
                    payload["error"] = err_str
                    event.extraction_payload = payload
                    await session.commit()
                    return event

                payload["curator_output"] = curator_output.model_dump()
                event.extraction_payload = payload
                await session.commit()

            if not curator_output.should_learn:
                event.status = "completed"
                await session.commit()
                return event

            # 3. Deterministic Validation Stage (NO MUTATIONS YET!)
            event.status = "validated"
            review_reasons: list[str] = []
            requires_review = curator_output.requires_review
            if curator_output.review_reason:
                review_reasons.append(curator_output.review_reason)

            # Evidence & Confidence validation on candidate memories
            for cand in curator_output.memories:
                conf = float(cand.confidence) if cand.confidence is not None else 0.5
                if conf < 0.75:
                    requires_review = True
                    review_reasons.append(f"Low confidence ({conf:.2f}) on candidate '{cand.content[:35]}'")

                if not cand.evidence_refs:
                    requires_review = True
                    review_reasons.append(f"Missing evidence_refs on candidate '{cand.content[:35]}'")
                else:
                    s_id = (source_event_id or "").lower()
                    grounded = any(
                        ref.strip().lower() in (s_id, "user", "assistant", "turn", "msg")
                        or (s_id and ref.strip().lower() in s_id)
                        or (s_id and s_id in ref.strip().lower())
                        or ref.strip().lower().startswith(("msg", "turn", "message", "run"))
                        or ref.strip().lower() in user_message.lower()
                        or ref.strip().lower() in ai_response.lower()
                        for ref in cand.evidence_refs
                        if ref.strip()
                    )
                    if not grounded:
                        requires_review = True
                        review_reasons.append(f"Ungrounded evidence_refs on candidate '{cand.content[:35]}'")

                if cand.operation == "propose_delete":
                    requires_review = True
                    review_reasons.append(f"Proposed deletion requires human confirmation: '{cand.content[:35]}'")

                for pat in SENSITIVE_PATTERNS:
                    if re.search(pat, cand.content) or (cand.supersedes_fact and re.search(pat, cand.supersedes_fact)):
                        requires_review = True
                        review_reasons.append("Sensitive credential pattern detected in extracted content")

            # Validate Knowledge Graph entities & relationships (purely read-only)
            graph_val = await GraphManagerService.resolve_and_validate(
                tenant_id=tenant_id,
                project_id=project_id,
                candidate_entities=curator_output.entities,
                candidate_relationships=curator_output.relationships,
                source_ref=f"turn:{source_event_id}",
            )
            if graph_val["requires_review"]:
                requires_review = True
                review_reasons.extend(graph_val["review_reasons"])

            event.requires_review = requires_review
            if review_reasons:
                event.error = "; ".join(review_reasons)
            await session.commit()

            # STRICT INVARIANT: If review required, PAUSE! DO NOT MUTATE ANY STORE!
            if event.requires_review:
                event.status = "review_required"
                await session.commit()
                return event

            # 4. Applying Coordinated Storage Updates (ACCEPTANCE POLICY SUCCEEDED)
            event.status = "applying"
            await session.commit()

            # Apply Knowledge Graph mutations
            graph_app = await GraphManagerService.apply_resolved(
                tenant_id=tenant_id,
                project_id=project_id,
                resolved_entities=graph_val["resolved_entities"],
                resolved_relationships=graph_val["resolved_relationships"],
            )
            event.applied_graph_entity_ids = graph_app["applied_entities"]
            event.applied_graph_rel_ids = graph_app["applied_relationships"]

            # Apply Memories (SQLite, ChromaDB, Markdown)
            existing_active_mems = await MemoryService.list(session, tenant_id, project_id, status="active")
            applied_mem_ids: list[str] = []

            for cand in curator_output.memories:
                cand_text = cand.content.strip()
                if not cand_text:
                    continue

                duplicate = any(m.text.strip().lower() == cand_text.lower() for m in existing_active_mems)
                if duplicate and cand.operation != "propose_replace":
                    logger.debug("Skipping duplicate memory: %s", cand_text)
                    continue

                superseded_target_id: str | None = None
                if cand.operation == "propose_replace" or cand.supersedes_fact:
                    for m in existing_active_mems:
                        if m.kind == cand.kind or cand.kind in ("preference", "technology"):
                            await MemoryService.update(
                                session, tenant_id, project_id, m.id, status="superseded"
                            )
                            MarkdownMemoryService.sync_memory(
                                tenant_id, project_id, m.id, m.text, m.kind, status="superseded"
                            )
                            superseded_target_id = m.id
                            break

                cand_conf = float(cand.confidence) if cand.confidence is not None else 1.0
                saved_mem = await MemoryService.remember(
                    session=session,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    text=cand_text,
                    kind=cand.kind,
                    confidence=cand_conf,
                    provenance="memory_curator",
                    status="active",
                    source_ref=f"turn:{source_event_id}",
                    superseded_by=superseded_target_id,
                    meta={"evidence_refs": cand.evidence_refs},
                )
                applied_mem_ids.append(saved_mem.id)

                MarkdownMemoryService.sync_memory(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    memory_id=saved_mem.id,
                    text=saved_mem.text,
                    kind=saved_mem.kind,
                    confidence=saved_mem.confidence,
                    status="active",
                )

            event.applied_memory_ids = applied_mem_ids
            event.status = "completed"
            await session.commit()

            await AuditService.log(
                tenant_id=tenant_id,
                project_id=project_id,
                action="memory.learned_from_conversation",
                resource_type="memory_learning_event",
                resource_id=event.id,
                meta={
                    "source_event_id": source_event_id,
                    "applied_memories_count": len(applied_mem_ids),
                    "applied_entities_count": len(event.applied_graph_entity_ids),
                    "applied_relationships_count": len(event.applied_graph_rel_ids),
                },
            )
            return event

        except Exception as e:
            logger.exception("Error executing learning turn %s: %s", source_event_id, e)
            event.status = "failed"
            event.error = str(e)[:200]
            event.retry_count += 1
            await session.commit()
            return event

    @classmethod
    async def approve_event(
        cls, session: AsyncSession, tenant_id: str, project_id: str, event_id: str
    ) -> MemoryLearningEvent | None:
        """Human approval of pending candidates in a review_required learning event.
        Applies both candidate memories and graph entities/relationships."""
        event = (
            await session.execute(
                select(MemoryLearningEvent).where(
                    MemoryLearningEvent.id == event_id,
                    MemoryLearningEvent.tenant_id == tenant_id,
                    MemoryLearningEvent.project_id == project_id,
                )
            )
        ).scalar_one_or_none()

        if not event or event.status != "review_required":
            return event

        payload = event.extraction_payload or {}
        output_data = payload.get("curator_output") or payload
        memories = output_data.get("memories", [])
        entities_data = [EntityCandidate.model_validate(e) for e in output_data.get("entities", [])]
        rels_data = [RelationshipCandidate.model_validate(r) for r in output_data.get("relationships", [])]

        # 1. Apply Knowledge Graph candidates
        if entities_data or rels_data:
            graph_val = await GraphManagerService.resolve_and_validate(
                tenant_id=tenant_id,
                project_id=project_id,
                candidate_entities=entities_data,
                candidate_relationships=rels_data,
                source_ref=f"turn:{event.source_event_id}",
            )
            graph_app = await GraphManagerService.apply_resolved(
                tenant_id=tenant_id,
                project_id=project_id,
                resolved_entities=graph_val["resolved_entities"],
                resolved_relationships=graph_val["resolved_relationships"],
            )
            event.applied_graph_entity_ids = graph_app["applied_entities"]
            event.applied_graph_rel_ids = graph_app["applied_relationships"]

        # 2. Apply Candidate Memories
        applied_mem_ids: list[str] = list(event.applied_memory_ids or [])
        for m_data in memories:
            text = m_data.get("content", "").strip()
            if not text:
                continue
            kind = m_data.get("kind", "note")
            conf = float(m_data.get("confidence") or 1.0)
            saved = await MemoryService.remember(
                session=session,
                tenant_id=tenant_id,
                project_id=project_id,
                text=text,
                kind=kind,
                confidence=conf,
                provenance="memory_curator_approved",
                status="active",
                source_ref=event.source_event_id or f"event:{event.id}",
                meta={"evidence_refs": m_data.get("evidence_refs", [])},
            )
            applied_mem_ids.append(saved.id)
            MarkdownMemoryService.sync_memory(
                tenant_id=tenant_id,
                project_id=project_id,
                memory_id=saved.id,
                text=saved.text,
                kind=saved.kind,
                confidence=saved.confidence,
                status="active",
            )

        event.applied_memory_ids = applied_mem_ids
        event.requires_review = False
        event.status = "completed"
        await session.commit()
        return event

    @classmethod
    async def reject_event(
        cls, session: AsyncSession, tenant_id: str, project_id: str, event_id: str
    ) -> MemoryLearningEvent | None:
        """Reject pending candidate knowledge to prevent re-learning. No mutations applied."""
        event = (
            await session.execute(
                select(MemoryLearningEvent).where(
                    MemoryLearningEvent.id == event_id,
                    MemoryLearningEvent.tenant_id == tenant_id,
                    MemoryLearningEvent.project_id == project_id,
                )
            )
        ).scalar_one_or_none()

        if not event:
            return None

        event.status = "rejected"
        event.requires_review = False
        await session.commit()
        return event

    @classmethod
    async def recover_pending_events(
        cls,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> int:
        """Scan SQLite for interrupted learning events across restarts and resume them."""
        recovered = 0
        async with SessionLocal() as session:
            stmt = select(MemoryLearningEvent).where(
                MemoryLearningEvent.status.in_(["pending", "extracted", "applying"])
            )
            if tenant_id:
                stmt = stmt.where(MemoryLearningEvent.tenant_id == tenant_id)
            if project_id:
                stmt = stmt.where(MemoryLearningEvent.project_id == project_id)
            events = (await session.execute(stmt)).scalars().all()

            ev_snapshots = [
                (
                    ev.id,
                    ev.tenant_id,
                    ev.project_id,
                    ev.source_event_id,
                    ev.retry_count,
                    dict(ev.extraction_payload or {}),
                )
                for ev in events
            ]

            for ev_id, tenant_id, project_id, source_event_id, retry_count, payload in ev_snapshots:
                enabled = await cls.is_learning_enabled(session, tenant_id, project_id)
                if not enabled:
                    ev_obj = await session.get(MemoryLearningEvent, ev_id)
                    if ev_obj:
                        ev_obj.status = "cancelled"
                        ev_obj.error = "Learning scope disabled for project"
                        await session.commit()
                    continue

                max_retries = getattr(settings, "memory_learning_max_retries", 3)
                if retry_count >= max_retries:
                    ev_obj = await session.get(MemoryLearningEvent, ev_id)
                    if ev_obj:
                        ev_obj.status = "failed"
                        ev_obj.error = f"Exceeded maximum retry attempts ({max_retries}) (dead-lettered)"
                        await session.commit()
                    continue

                turn_info = payload.get("turn", {})
                u_text = turn_info.get("user_message", "")
                a_text = turn_info.get("ai_response", "")
                if not u_text:
                    ev_obj = await session.get(MemoryLearningEvent, ev_id)
                    if ev_obj:
                        ev_obj.status = "failed"
                        ev_obj.error = "Missing turn payload on restart recovery"
                        await session.commit()
                    continue

                ev_obj = await session.get(MemoryLearningEvent, ev_id)
                if ev_obj:
                    ev_obj.retry_count += 1
                    await session.commit()

                task = asyncio.create_task(
                    cls._safe_run_turn_learning(
                        tenant_id=tenant_id,
                        project_id=project_id,
                        source_event_id=source_event_id,
                        user_message=u_text,
                        ai_response=a_text,
                    )
                )
                cls._active_tasks.add(task)
                task.add_done_callback(cls._active_tasks.discard)
                recovered += 1
        return recovered

    @classmethod
    async def drain_active_tasks(cls, timeout: float = 5.0) -> None:
        """Wait for active background learning tasks during graceful shutdown."""
        if not cls._active_tasks:
            return
        tasks = list(cls._active_tasks)
        try:
            async with asyncio.timeout(timeout):
                await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            for t in tasks:
                t.cancel()
