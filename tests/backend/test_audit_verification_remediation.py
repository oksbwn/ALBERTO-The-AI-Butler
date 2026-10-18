"""
Regression and verification tests for Memory Intelligence subsystem audit findings.
Covers:
- Memory Curator single-call guarantee on failure (at most 1 inference attempt).
- Startup learning recovery idempotency, worker lease locking, and review-required preservation.
- Source synchronization execution outcome verification.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from alberto.db import SessionLocal
from alberto.models import MemoryLearningEvent, Project, McpClient
from alberto.schemas.memory_curator import MemoryCuratorOutput
from alberto.services.learning_coordinator import LearningCoordinator
from alberto.services.memory_curator import MemoryCuratorService
from alberto.services.source_sync import SourceSyncCoordinator
from alberto.tools.mcp import McpExecutionOutcome


class CountingMockModel:
    """Mock LLM tracking inference invocation counts."""

    def __init__(self, fail_structured: bool = True):
        self.call_count = 0
        self.raw_call_count = 0
        self.fail_structured = fail_structured

    def with_structured_output(self, schema):
        structured = MagicMock()

        async def _ainvoke(messages):
            self.call_count += 1
            if self.fail_structured:
                raise RuntimeError("Structured output parsing failed: schema mismatch")
            return MemoryCuratorOutput(should_learn=False)

        structured.ainvoke = _ainvoke
        return structured

    async def ainvoke(self, messages):
        self.call_count += 1
        self.raw_call_count += 1
        return MagicMock(content='{"should_learn": false, "memories": [], "entities": [], "relationships": []}')


@pytest.mark.asyncio
async def test_curator_single_call_guarantee_on_failure():
    """Verify that a failed structured-output invocation NEVER triggers a second LLM inference call."""
    mock_model = CountingMockModel(fail_structured=True)

    with patch.object(MemoryCuratorService, "get_curator_model", new_callable=AsyncMock) as mock_get_model:
        mock_get_model.return_value = (mock_model, "mock-test-model")

        async with SessionLocal() as session:
            output = await MemoryCuratorService.extract(
                session=session,
                tenant_id="tenant_audit_test",
                project_id="proj_audit_test",
                user_message="I use SQLite for local caching.",
                ai_response="Understood, SQLite is great for that.",
            )

    # Exactly ONE invocation occurred
    assert mock_model.call_count == 1
    # Raw invoke fallback was NOT called after structured invoke failed
    assert mock_model.raw_call_count == 0
    # Error was cleanly recorded
    assert output.should_learn is False
    assert output.extraction_error is not None
    assert "Structured output parsing failed" in output.extraction_error


@pytest.mark.asyncio
async def test_startup_learning_recovery_and_worker_locking():
    """Verify startup recovery idempotence, in-flight worker locking, and review-required safety."""
    tenant_id = "tenant_recovery_test"
    project_id = "proj_recovery_test"
    source_event_id = "turn_rec_001"

    async with SessionLocal() as session:
        # Create test project with learning enabled
        proj = Project(
            id=project_id,
            name="Recovery Test Project",
            slug="recovery-test-proj",
            tenant_id=tenant_id,
            config={"memory_learning_enabled": True},
        )
        session.add(proj)
        await session.commit()

        # Insert a pending event (simulating crash before background worker picked it up)
        ev_pending = MemoryLearningEvent(
            tenant_id=tenant_id,
            project_id=project_id,
            source_event_id=source_event_id,
            source_type="conversation_turn",
            status="pending",
            requires_review=False,
            extraction_payload={"turn": {"user_message": "I run Podman instead of Docker.", "ai_response": "Noted."}},
            applied_memory_ids=[],
            applied_graph_entity_ids=[],
            applied_graph_rel_ids=[],
        )
        session.add(ev_pending)

        # Insert a review-required event (must NEVER be auto-recovered or re-run)
        ev_review = MemoryLearningEvent(
            tenant_id=tenant_id,
            project_id=project_id,
            source_event_id="turn_rec_review",
            source_type="conversation_turn",
            status="extracted",
            requires_review=True,
            extraction_payload={"turn": {"user_message": "Delete everything.", "ai_response": "Wait."}},
            applied_memory_ids=[],
            applied_graph_entity_ids=[],
            applied_graph_rel_ids=[],
        )
        session.add(ev_review)
        await session.commit()

    # Clear active keys
    LearningCoordinator._in_progress_keys.clear()

    # Mock _safe_run_turn_learning to inspect recovery dispatch
    with patch.object(LearningCoordinator, "_safe_run_turn_learning", new_callable=AsyncMock) as mock_run:
        # 1. First recovery sweep: recovers the 1 pending event, skips the review-required event
        recovered = await LearningCoordinator.recover_pending_events(tenant_id, project_id)
        assert recovered == 1
        assert mock_run.call_count == 1

        # 2. Second recovery sweep while key is in progress: should recover 0 events (idempotent, no duplicates)
        recovered_again = await LearningCoordinator.recover_pending_events(tenant_id, project_id)
        assert recovered_again == 0
        assert mock_run.call_count == 1  # No duplicate dispatch

    # Clean up
    LearningCoordinator._in_progress_keys.clear()


@pytest.mark.asyncio
async def test_source_sync_execution_outcome_guard():
    """Verify source synchronization enforces valid tool execution outcome before learning."""
    tenant_id = "tenant_sync_audit"
    project_id = "proj_sync_audit"

    async with SessionLocal() as session:
        proj = Project(
            id=project_id,
            name="Sync Audit Project",
            slug="sync-audit-proj",
            tenant_id=tenant_id,
            config={"tool_execution_learning_enabled": True},
        )
        session.add(proj)

        client = McpClient(
            id="client_sync_audit",
            name="Home Integration",
            tenant_id=tenant_id,
            project_id=project_id,
            transport="stdio",
            command="python",
            enabled=True,
            learning_enabled=True,
            disabled_tools=[],
        )
        session.add(client)
        await session.commit()

        job = await SourceSyncCoordinator.configure_sync(
            session=session,
            tenant_id=tenant_id,
            project_id=project_id,
            client_id=client.id,
            template_id="device_inventory",
            enabled=True,
        )

        # 1. Call execute_sync with a non-success outcome (e.g. TOOL_ERROR)
        res_error = await SourceSyncCoordinator.execute_sync(
            session=session,
            tenant_id=tenant_id,
            project_id=project_id,
            job_id=job["job_id"],
            raw_items=[{"name": "Thermostat"}],
            execution_outcome=McpExecutionOutcome.TOOL_ERROR,
        )
        assert res_error["ok"] is False
        assert "failed" in res_error["error"]

        # 2. Call execute_sync with embedded tool error in raw_items
        res_payload_err = await SourceSyncCoordinator.execute_sync(
            session=session,
            tenant_id=tenant_id,
            project_id=project_id,
            job_id=job["job_id"],
            raw_items=[{"isError": True, "error": "Connection timed out to gateway"}],
            execution_outcome=McpExecutionOutcome.SUCCESS,
        )
        assert res_payload_err["ok"] is False
        assert "error" in res_payload_err["error"].lower()


@pytest.mark.asyncio
async def test_curator_provider_capability_skips_structured_when_unsupported():
    """Verify that when provider explicitly lacks tool/structured capability, raw JSON invocation is used."""
    mock_model = CountingMockModel(fail_structured=True)
    # Explicitly flag that this model/provider does not support tools
    setattr(mock_model, "supports_tools", False)

    with patch.object(MemoryCuratorService, "get_curator_model", new_callable=AsyncMock) as mock_get_model:
        mock_get_model.return_value = (mock_model, "mock-no-tools-model")

        async with SessionLocal() as session:
            output = await MemoryCuratorService.extract(
                session=session,
                tenant_id="tenant_cap_test",
                project_id="proj_cap_test",
                user_message="I run Ollama on my Mac mini.",
                ai_response="Understood.",
            )

    # Exactly ONE invocation occurred (raw invoke, not structured invoke)
    assert mock_model.call_count == 1
    assert mock_model.raw_call_count == 1
    assert output.should_learn is False


@pytest.fixture
def temp_graph_adapter():
    import tempfile
    from pathlib import Path
    from alberto.knowledge.graph import LadybugGraphAdapter, set_graph_adapter

    with tempfile.TemporaryDirectory(prefix="ladybug_audit_") as tmp:
        ad = LadybugGraphAdapter(db_path=Path(tmp))
        set_graph_adapter(ad)
        yield ad
        ad.close()
        set_graph_adapter(None)


@pytest.mark.asyncio
async def test_explicit_named_entities_like_alberto_not_blocked(temp_graph_adapter):
    """Verify that explicitly named entities (e.g. 'Alberto', 'OLMX') are not blocked by generic name guards."""
    from alberto.schemas.memory_curator import EntityCandidate
    from alberto.services.graph_manager import GraphManagerService

    candidates = [
        EntityCandidate(
            temporary_id="e1",
            name="Alberto",
            kind="application",
            confidence=0.95,
            description="AI Butler platform running on local infrastructure",
        ),
        EntityCandidate(
            temporary_id="e2",
            name="MacBook Pro",
            kind="device",
            confidence=0.92,
            description="Personal workstation",
        ),
    ]

    res = await GraphManagerService.resolve_and_validate(
        tenant_id="tenant_ent_test",
        project_id="proj_ent_test",
        candidate_entities=candidates,
        candidate_relationships=[],
        source_ref="turn:test_ent",
    )

    # Alberto and MacBook Pro must resolve cleanly without generic name review reasons
    assert res["requires_review"] is False
    assert len(res["resolved_entities"]) == 2
    names = {e.name for e in res["resolved_entities"]}
    assert "Alberto" in names
    assert "MacBook Pro" in names

