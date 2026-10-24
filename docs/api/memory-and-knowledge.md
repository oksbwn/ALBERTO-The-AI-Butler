# Memory & Knowledge API

Endpoints for document ingestion, Chroma vector retrieval, and Knowledge Graph entities.

> [!NOTE]
> Total verified endpoints documented: **46**.

### `GET` /v1/projects/{project_id}/graph/entities

**List Entities**

Find entities matching filters within the authorized tenant/project scope.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `kind` | query | `object` | No |  |
| `name` | query | `object` | No |  |
| `search` | query | `object` | No |  |
| `limit` | query | `integer` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `GraphEntityOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/graph/entities

**Create Or Update Entity**

Create or upsert an entity in the Knowledge Graph with scoped ownership.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `GraphEntityCreate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: `GraphEntityOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `DELETE` /v1/projects/{project_id}/graph/entities/{entity_id}

**Delete Entity**

Delete an entity and its associated relationships within scope.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `entity_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `204` | Successful Response | None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/graph/entities/{entity_id}

**Get Entity**

Get an entity by ID within the authorized tenant/project scope.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `entity_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `GraphEntityOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/graph/entities/{entity_id}/neighbors

**Get Neighbors**

Traverse relationships around an entity with end-to-end scope verification.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `entity_id` | path | `string` | Yes |  |
| `direction` | query | `string` | No |  |
| `max_depth` | query | `integer` | No |  |
| `limit` | query | `integer` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `GraphPathOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/graph/ontology/entity-types

**List Ontology Entity Types**

List approved and scoped Knowledge Graph entity types.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `status` | query | `object` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `OntologyEntityTypeOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/graph/ontology/entity-types

**Register Ontology Entity Type**

Register or approve an entity type definition in project scope.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `OntologyEntityTypeIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: `OntologyEntityTypeOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/graph/ontology/relationship-types

**List Ontology Relationship Types**

List approved and scoped Knowledge Graph relationship types.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `status` | query | `object` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `OntologyRelationshipTypeOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/graph/ontology/relationship-types

**Register Ontology Relationship Type**

Register or approve a relationship type definition in project scope.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `OntologyRelationshipTypeIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: `OntologyRelationshipTypeOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/graph/relationships

**Create Relationship**

Create a scoped relationship between two entities. Both must belong to the same scope.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `GraphRelationshipCreate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: `GraphRelationshipOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `DELETE` /v1/projects/{project_id}/graph/relationships/{rel_id}

**Delete Relationship**

Delete a relationship by ID within scope.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `rel_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `204` | Successful Response | None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/graph/shortest-path

**Shortest Path**

Find native shortest path between two entities within scope.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `start_id` | query | `string` | Yes |  |
| `end_id` | query | `string` | Yes |  |
| `max_depth` | query | `integer` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `GraphPathOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/graph/stats

**Get Graph Stats**

Retrieve Knowledge Graph storage status and scoped node/edge counts.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `GraphStatsOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/graph/subgraph

**Get Subgraph**

Retrieve a bounded, scoped subgraph for interactive visualization.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `focus_id` | query | `object` | No |  |
| `search` | query | `object` | No |  |
| `kind` | query | `object` | No |  |
| `rel_kind` | query | `object` | No |  |
| `limit` | query | `integer` | No |  |
| `hop_depth` | query | `integer` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `GraphSubgraphOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/knowledge/chunk

**Chunk Detail**

Full text (+ light metadata) of a single chunk, fetched on demand when a dot is selected
in the chunk map (the map payload carries only a short preview). Scoped to the tenant/project.
404 when the id isn't in this project's current-embedder collection.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `chunk_id` | query | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/knowledge/dedupe

**Dedupe Chunks**

Remove exact-duplicate chunks (identical text) project-wide, keeping one copy of each.
Returns {removed, groups, sources_affected, remaining}.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/knowledge/folders

**List Folders**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `string` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/knowledge/health

**Embedding Health**

Embedding-dimension health: flags sources embedded with a different model than the
project's current embedder (which would silently return no search results).

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/knowledge/map

**Chunk Map**

Chunk-map visualizer: 2-D (PCA) projection of the project's chunk vectors, colored by
source, with an optional query overlay showing what retrieval returns. Read-only.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `KnowledgeMapIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/knowledge/search

**Search**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `KnowledgeSearchIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/knowledge/sources

**List Sources**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `KbSourceOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/knowledge/sources

**Add Source**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `KbSourceCreate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: `KbSourceOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/knowledge/sources/rechunk

**Rechunk Sources**

Re-chunk a multi-selected set of sources with one shared set of overrides
(strategy / size / overlap), then re-embed each (in the background). Tenant/project-scoped.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `RechunkBulkIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/knowledge/sources/upload

**Upload Source**

Upload a document file (.txt/.md/.pdf and other text formats) into the knowledge base.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`multipart/form-data`)

Schema: `Body_upload_source_v1_projects__project_id__knowledge_sources_upload_post`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: `KbSourceOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `DELETE` /v1/projects/{project_id}/knowledge/sources/{source_id}

**Delete Source**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `source_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `204` | Successful Response | None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PATCH` /v1/projects/{project_id}/knowledge/sources/{source_id}

**Update Source**

Move a source between folders (the only mutable field; content requires re-ingest).
Not snapshotted: a folder move is minor bookkeeping, not an add/remove worth logging.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `source_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `object`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `KbSourceOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/knowledge/sources/{source_id}/reingest

**Reingest Source**

Re-fetch + re-embed a source (re-crawl a site, or re-embed under the current model).
An optional body overrides the chunking (strategy / size / overlap) before re-ingest.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `source_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `object`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/memory/learning/events

**List Learning Events**

List background learning events and pending review items.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `status` | query | `object` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `LearningEventOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/memory/learning/events/{event_id}/approve

**Approve Learning Event**

Approve candidate knowledge in a review_required event with optional human edits.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `event_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `object`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `LearningEventOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/memory/learning/events/{event_id}/reject

**Reject Learning Event**

Reject candidate knowledge in a learning event.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `event_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `LearningEventOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/memory/learning/events/{event_id}/suggest

**Get Learning Event Suggestions**

Retrieve or generate advisory recommendations from Memory Curator for review items.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `event_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `CuratorAdvisorySuggestion` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/memory/learning/settings

**Get Learning Settings**

Get conversation learning configuration, status, and effective models.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `MemoryLearningSettingsOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PATCH` /v1/projects/{project_id}/memory/learning/settings

**Update Learning Settings**

Update conversation learning configuration (toggle, model overrides). Persists to Project.config.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `MemoryLearningSettingsIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `MemoryLearningSettingsOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/memory/markdown

**List Markdown Memory Files**

List markdown memory files under /data/memory/<tenant_id>/<project_id>/.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `filename` | query | `object` | No | Optional filename to fetch full content |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `MarkdownMemoryFileOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/memory/recall

**Recall Memory**

Retrieve memories across configured storage sources.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `MemoryRecallIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `MemoryRecallOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/memory/records

**List Memory Records**

List authoritative memories with filtering.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `status` | query | `object` | No |  |
| `kind` | query | `object` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `MemoryRecordDetailOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `DELETE` /v1/projects/{project_id}/memory/records/{record_id}

**Delete Memory Record**

Delete an authoritative memory record and remove from projections.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `record_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `204` | Successful Response | None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/memory/records/{record_id}

**Get Memory Record**

Get single authoritative memory record.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `record_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `MemoryRecordDetailOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PATCH` /v1/projects/{project_id}/memory/records/{record_id}

**Update Memory Record**

Correct or update an authoritative memory record.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `record_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `MemoryRecordUpdateIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `MemoryRecordDetailOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/memory/remember

**Remember Memory**

Store an explicit memory record deterministically in the requested store.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `MemoryRememberIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `object` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/memory/status

**Get Memory Status**

Get status and stats across all four memory mechanisms.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `MemoryStatusOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/qa-pairs

**List Qa**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `QaPairOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/qa-pairs

**Add Qa**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `QaPairCreate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: `QaPairOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/qa-pairs/kinds

**List Qa Kinds**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `string` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `DELETE` /v1/projects/{project_id}/qa-pairs/{qa_id}

**Delete Qa**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `qa_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `204` | Successful Response | None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PATCH` /v1/projects/{project_id}/qa-pairs/{qa_id}

**Update Qa**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `qa_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `QaPairUpdate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `QaPairOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---
