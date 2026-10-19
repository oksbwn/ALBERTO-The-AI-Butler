# Alberto — Dynamic Knowledge Graph Ontology, Human Approval & Intelligent Type Suggestions

## 1. Executive Summary

This deliverable documents the complete evolution of Alberto's Knowledge Graph into an LLM-driven, dynamically extensible, human-governed knowledge system. The implementation adheres strictly to the core principle:

$$\text{LLM proposes} \longrightarrow \text{Graph Manager validates} \longrightarrow \text{Human reviews when required} \longrightarrow \text{Alberto learns from the decision}$$

Key achievements:
- **No Extra LLM Agents or Multi-Agent Loops**: Single extraction call per eligible conversation turn or MCP tool observation.
- **No Secondary Databases or LadybugDB Schema Migrations**: Preserves embedded LadybugDB storage invariants while governing extensible logical types in SQLite.
- **Dynamic Ontology Registry**: Canonical entity types, relationship types, and learned entity-to-type mappings stored with tenant/project isolation and provenance.
- **Editable HITL Review Queue**: Direct inline editing of entity kinds, custom novel type creation, editable descriptions, directional relationship swapping ($\rightleftarrows$), and relationship reclassification.
- **Curator Advisory Suggestions**: Bounded advisory LLM analysis triggered only for review warnings or ambiguities, with proposal-hash caching to prevent repeated inference.
- **Persistent Operational Learning**: Approvals and corrections permanently influence future graph discovery and identity resolution.

---

## 2. Existing Architecture Findings

Prior to this implementation:
1. **Curator Extraction Schema Constraints**:
   - `EntityCandidate.kind` and `RelationshipCandidate.kind` in `MemoryCuratorOutput` were constrained by literal sets or coarse categorization.
   - Conceptual prompts directed the LLM to restrict entities to broad generic labels (`concept`, `device`, `software`, `fact`).
2. **Hardcoded Product and Operating System Classifications**:
   - In `GraphManagerService`, static lists existed for OS normalization (`macOS`, `Ubuntu`, `Windows`, `Fedora`) and device normalization (`Mac mini`, `MacBook Pro`, `Raspberry Pi`). Unfamiliar technologies were either misclassified as generic `concept`/`device` or rejected.
3. **Approval API & Review Queue Limitations**:
   - `approve_learning_event` was an all-or-nothing binary trigger (`POST /v1/projects/{pid}/memory/learning/events/{id}/approve`) that accepted candidate items exactly as proposed by the LLM without allowing reviewer overrides.
   - The frontend Review Queue was read-only, displaying candidate entities and relationships without interactive controls.
4. **Lack of Ontology Persistence**:
   - When a user repeatedly clarified domain-specific technical concepts (e.g., `vLLM` is an `inference_framework`, or `Alberto` `DEPLOYED_VIA` `Docker`), no persistent registry existed to record and reuse that approved semantic definition across subsequent turns.

---

## 3. Hardcoded Classification Logic: Removed vs. Retained

### Logic Removed or Refactored
- **Hardcoded OS/Device Classification Branches**: Replaced by queries to `OntologyRegistryService.get_entity_mapping(...)` and `OntologyRegistryService.resolve_entity_type(...)`.
- **Closed Type Unions**: Relaxed strict static entity-type boundaries in Curator extraction while strictly preserving deterministic structural guards.

### Logic Retained for Safety and Reliability
- **Generic Label Safeguards**: Prohibits ambiguous, low-information single-word nouns (`thing`, `device`, `machine`, `system`, `server`, `item`, `user`, `assistant`, `computer`) from entering the graph without descriptive disambiguation.
- **Confidence Thresholds**: Candidate entities with confidence $< 0.75$ and relationships with confidence $< 0.70$ are deterministically paused for human review.
- **Evidence Grounding Checks**: Candidate entities and aliases not explicitly grounded in user statements or verified tool output require human confirmation.
- **Credential & Secret Protections**: Regex filters continue to intercept passwords, API keys, and sensitive tokens.

---

## 4. Ontology Registry Design

Implemented in SQLite via Alembic migration `0021_dynamic_ontology_registry.py` and service `backend/alberto/services/ontology_registry.py`.

### 4.1 Schema
1. **`ontology_entity_types`**:
   - `id`: UUID primary key.
   - `tenant_id`, `project_id`: Multi-tenant isolation scope.
   - `canonical_key`: Clean lowercase key (e.g., `inference_framework`, `container_runtime`, `operating_system`).
   - `display_name`, `description`: Human-readable semantic documentation.
   - `aliases`: JSON array of approved synonyms and alternative casings.
   - `status`: `approved`, `pending`, `deprecated`.
   - `provenance`: `system_seed`, `human_review`, `curator_proposal`.
2. **`ontology_relationship_types`**:
   - `id`: UUID primary key.
   - `tenant_id`, `project_id`: Multi-tenant isolation scope.
   - `canonical_key`: Clean uppercase key (e.g., `DEPLOYED_VIA`, `RUNS_ON`, `MANAGES`, `CONNECTS_TO`).
   - `description`: Relationship semantics.
   - `allowed_source_types`, `allowed_target_types`: Optional endpoint compatibility constraints.
   - `direction_semantics`: `source_to_target`, `bidirectional`.
   - `aliases`: JSON array of alternative edge labels.
   - `status`, `provenance`: Lifecycle governance metadata.
3. **`ontology_entity_mappings`**:
   - `id`: UUID primary key.
   - `tenant_id`, `project_id`: Multi-tenant isolation scope.
   - `entity_canonical_name`: Normalized entity name (e.g., `macos`, `olmx`, `mac mini`).
   - `target_entity_type`: Canonical entity kind key.
   - `provenance`: Reviewer ID or seed attribution.
   - `status`: `active`, `deprecated`.

### 4.2 Seed Registry Defaults
- **19 Canonical Entity Types**: `operating_system`, `device`, `hardware`, `host`, `appliance`, `application`, `software`, `container_runtime`, `inference_framework`, `framework`, `model`, `modelrunner`, `service`, `platform`, `person`, `location`, `technology`, `concept`, `project`.
- **13 Canonical Relationship Types**: `RUNS`, `RUNS_ON`, `DEPLOYED_VIA`, `PREFERS`, `USES`, `LOCATED_IN`, `MANAGES`, `OWNS`, `CONNECTS_TO`, `PART_OF`, `DEPENDS_ON`, `INTERACTS_WITH`, `RELATES_TO`.
- **Seed Entity Mappings**: Pre-seeded knowledge mapping popular operating systems (`macos`, `ubuntu`, `debian`), hardware families (`mac mini`, `macbook pro`, `raspberry pi`), and AI runtimes (`olmx` $\to$ `application`, `docker` $\to$ `container_runtime`).

---

## 5. Memory Curator Discovery Changes

The Memory Curator prompt and extraction schema now support LLM-driven discovery of novel types:
- **Conceptual Prompting**: Curator is instructed to identify exact domain-specific types supported by the evidence (e.g., `inference_framework`, `container_runtime`, `vector_database`) without forcing them into generic `concept` or `tool`.
- **Relationship Semantics**: Prompts encourage precise typed edges (`DEPLOYED_VIA`, `RUNS_ON`) over generic `RELATES_TO`.
- **Single-Inference Guarantee**: Standard conversation extraction remains bounded to exactly one LLM call per turn.

---

## 6. Graph Manager Validation Changes

Validation order in `GraphManagerService.resolve_and_validate`:
1. **Learned Mapping Check**: Inspects `OntologyRegistryService.get_entity_mapping` for known or user-corrected entity names (with prefix matching for OS and hardware versions).
2. **Canonical & Synonym Resolution**: Queries `OntologyRegistryService.resolve_entity_type` and `resolve_relationship_type` against approved registry definitions and synonyms.
3. **Deterministic Compatibility & Guardrails**: Enforces generic label rejection, minimum confidence, and endpoint validity.
4. **Novel Type Handling**: If an entity type or relationship type is novel (unregistered), Graph Manager flags the event with `requires_review = True`, records explicit review reasons, and stages relationship instances safely under fallback `RELATES_TO` pending reviewer authorization.

---

## 7. Node and Edge Type Editing Capabilities

The HITL approval flow allows human reviewers full authority over proposed graph knowledge:
- **Node Reclassification**: Reviewers can reclassify any entity using a dropdown of approved canonical types or choose `+ Propose New Ontology Type...` to register a novel type definition.
- **Description Editing**: Reviewers can refine the descriptive definition of any node before persistence.
- **Edge Type Editing**: Reviewers can change relationship types from a dropdown of approved relationship kinds or propose novel relationship semantics.
- **Direction Correction**: A bidirectional flip button ($\rightleftarrows \text{ Swap Direction}$) allows immediate correction if the LLM inverted the dependency.
- **Schema**: Review edits are submitted via `LearningEventApprovalIn` containing `NodeApprovalEdit` and `EdgeApprovalEdit` objects.

---

## 8. Intelligent Advisory Suggestion Flow

When validation warnings or classification ambiguities arise:
1. **Advisory Trigger**: Reviewer clicks "Curator Advisory" in the Review Queue.
2. **Bounded Execution**: Invokes `MemoryCuratorService.suggest_review_correction` using Alberto's configured curator model.
3. **Structured Response**:
   - `target_type`: `entity` or `relationship`.
   - `target_ref`: Entity name or relationship index.
   - `suggested_kind`: Recommended canonical type.
   - `suggested_direction`: `normal` or `reverse`.
   - `explanation`: Clear rationale grounded in evidence.
   - `evidence_refs`: Supporting turn citations.
   - `requires_new_ontology_definition`: Boolean flag.
4. **Proposal Caching**: Results are hashed by proposal content and review reasons. Identical proposal revisions return cached suggestions with zero redundant LLM calls.
5. **Human Autonomy**: Advisory suggestions never directly mutate graph data. The reviewer can apply suggestions with a single click, customize them further, or reject them.

---

## 9. Learning from Human Corrections

When a human reviewer approves or modifies a proposal:
1. **New Type Definitions**: Novel types marked with `is_new_ontology_type` are automatically registered in `ontology_entity_types` or `ontology_relationship_types`.
2. **Learned Entity Mappings**: When an entity's type is corrected (e.g., reviewer changes `CustomPlatform` from `device` to `operating_system`), `OntologyRegistryService.record_entity_mapping` persists the correction. Future turns encountering `CustomPlatform` resolve directly to `operating_system`.
3. **Audit History**: Both original extraction proposals and human modifications are preserved in `extraction_payload["original_proposal"]` and `extraction_payload["human_edits"]`.

---

## 10. Performance Impact & Local LLM Constraints

- **Extraction Budget**: 1 LLM call per eligible turn. No mandatory secondary classification call.
- **Advisory Budget**: 0 LLM calls during routine extraction. Advisory suggestions run strictly on-demand during review.
- **Suggestion Caching**: In-memory proposal hash prevents repeat inference on identical review items.
- **Timeout Protection**: Advisory inference has a strict 15-second timeout; failures degrade gracefully to manual review without blocking the interface.
- **Transaction Safety**: SQLite writes use short, scoped transactions. No long-held locks during inference.

---

## 11. Database Migrations

- **Migration File**: `backend/migrations/versions/0021_dynamic_ontology_registry.py`.
- **Tables Created**:
  - `ontology_entity_types`
  - `ontology_relationship_types`
  - `ontology_entity_mappings`
- **Indices Added**:
  - `ix_ont_ent_scope_key` (`tenant_id`, `project_id`, `canonical_key`)
  - `ix_ont_rel_scope_key` (`tenant_id`, `project_id`, `canonical_key`)
  - `ix_ont_map_scope_name` (`tenant_id`, `project_id`, `entity_canonical_name`)

---

## 12. Test Coverage and Results

A comprehensive verification suite was executed across backend and frontend:

| Test Suite | Tests | Result | Focus Areas |
|:---|:---:|:---:|:---|
| `test_dynamic_ontology_hitl.py` | 6 | **Passed** | Novel type registration, HITL node/edge edits, learned mapping persistence, curator advisory caching, macOS/OLMX regression. |
| `test_m2_1_memory_curator.py` | 10 | **Passed** | Structured extraction, generic guards, ambiguity flagging, cross-store atomicity. |
| `test_m2_1_reliability.py` | 10 | **Passed** | Worker recovery, acceptance policies, duplicate event prevention. |
| `test_ladybug_graph.py` | 21 | **Passed** | Scoped graph operations, shortest path, neighbor discovery. |
| `test_memory_recall_accuracy.py` | 12 | **Passed** | Exact recall, hallucination rejection, similar name differentiation. |
| **Backend Ruff Linter** | - | **Passed** | 0 lint errors. |
| **Frontend TypeScript Build** | - | **Passed** | Next.js production build (`next build`) succeeded with 0 errors. |

---

## 13. Remaining Limitations & Future Enhancements

1. **Global Promotion Governance**: Currently, all learned mappings and novel types are scoped to `tenant_id` and `project_id`. A cross-project promotion workflow could allow administrators to promote verified project ontologies to global tenant defaults.
2. **Schema Constraint Validation on Edge Endpoints**: `allowed_source_types` and `allowed_target_types` currently generate validation warnings for review rather than hard-rejecting relationships. This allows domain flexibility while alerting reviewers.
3. **Batch Review Operations**: The current UI allows reviewing one learning event at a time; future releases can add batch-approve and bulk-reclassification tools.
