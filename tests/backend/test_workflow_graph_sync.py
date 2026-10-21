import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from alberto.db.base import SessionLocal
from alberto.knowledge.graph import LadybugGraphAdapter, make_entity_id
from alberto.models import Project, Tenant
from alberto.services.workflows import WorkflowService


@pytest.fixture
async def setup_graph_sync_env():
    async with SessionLocal() as s:
        tenant = Tenant(name="T-GraphSync")
        s.add(tenant)
        await s.commit()
        await s.refresh(tenant)

        proj = Project(tenant_id=tenant.id, name="P-GraphSync", slug="p-graphsync")
        s.add(proj)
        await s.commit()
        await s.refresh(proj)

        return tenant, proj


@pytest.mark.asyncio
async def test_workflow_creation_mirrors_to_knowledge_graph(setup_graph_sync_env):
    """Creating a workflow automatically upserts a Workflow entity and relationships to LadybugDB."""
    tenant, proj = setup_graph_sync_env

    with tempfile.TemporaryDirectory(prefix="ladybug_wf_sync_") as tmp:
        adapter = LadybugGraphAdapter(db_path=Path(tmp))
        await adapter.initialize()

        try:
            with patch("alberto.knowledge.graph.get_graph_adapter", return_value=adapter):
                async with SessionLocal() as s:
                    wf = await WorkflowService.create(
                        s,
                        tenant.id,
                        proj.id,
                        name="Lead Enrichment Pipeline",
                        description="Enriches inbound leads and alerts customer success.",
                        executable={
                            "nodes": [
                                {"id": "entry", "type": "trigger_webhook"},
                                {"id": "n1", "type": "agent", "config": {"name": "EnricherAgent"}},
                                {"id": "n2", "type": "tool", "config": {"name": "send_slack_alert"}},
                                {"id": "end", "type": "end"},
                            ],
                            "edges": [
                                {"source": "entry", "target": "n1"},
                                {"source": "n1", "target": "n2"},
                                {"source": "n2", "target": "end"},
                            ],
                        },
                    )

                    wf_entity_id = make_entity_id(tenant.id, proj.id, "workflow", wf.name)
                    entity = await adapter.get_entity(tenant.id, proj.id, wf_entity_id)

                    assert entity is not None
                    assert entity.name == "Lead Enrichment Pipeline"
                    assert entity.kind == "workflow"
                    assert "Enriches inbound leads" in entity.description

            # Verify outgoing relationships (USES agent and USES tool)
            rels = await adapter.get_relationships(tenant.id, proj.id, wf_entity_id, direction="outgoing")
            assert len(rels) >= 2
            kinds = [r.kind for r in rels]
            assert "USES" in kinds

            # Verify neighbor nodes exist
            paths = await adapter.get_neighbors(tenant.id, proj.id, wf_entity_id)
            neighbor_nodes = [node for p in paths for node in p.nodes if node.id != wf_entity_id]
            neighbor_names = [n.name for n in neighbor_nodes]
            assert "EnricherAgent" in neighbor_names
            assert "send_slack_alert" in neighbor_names
        finally:
            adapter.close()
