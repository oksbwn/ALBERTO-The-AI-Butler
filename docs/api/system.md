# System, Diagnostics & Administration API

Endpoints for platform health, audit telemetry, evaluations, and projects.

> [!NOTE]
> Total verified endpoints documented: **44**.

### `GET` /health

**Health**

Liveness: the process is up and serving. Cheap and dependency-free.

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `object` |

---

### `GET` /livez

**Health**

Liveness: the process is up and serving. Cheap and dependency-free.

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `object` |

---

### `GET` /metrics

**Metrics**

Prometheus text-format exposition of the in-process counters so operators can scrape
them (per-worker; aggregate across replicas at the scraper). Complements the OTLP trace
export. No new dependency - rendered directly from the counter snapshot.

Gated behind `settings.expose_metrics` (default off): the counters are an internal
operational surface, so keep it disabled on public deployments and enable only where the
scrape endpoint is reachable from a trusted network.

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |

---

### `GET` /readyz

**Readyz**

Readiness: can this instance actually serve traffic? Checks the DB, the durable
checkpointer, and (when configured) Redis, the vector store, and a worker heartbeat. Returns
503 when a GATING dependency is down so a load balancer / k8s probe routes around it
(audit P-imp / finding k). The worker is reported but non-gating - the API can still serve
while the worker tier is down (runs queue).

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |

---

### `GET` /v1/audit

**List Audit**

Filtered, keyset-paginated audit list (newest first). Returns a JSON array (unchanged
shape); the opaque cursor for the next page, when there is one, is in the `X-Next-Cursor`
response header (finding g).

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | query | `object` | No |  |
| `action` | query | `object` | No |  |
| `actor` | query | `object` | No | match actor_email or actor_id |
| `start` | query | `object` | No | only entries at/after this time (ISO 8601) |
| `end` | query | `object` | No | only entries at/before this time (ISO 8601) |
| `cursor` | query | `object` | No | opaque keyset cursor from a prior page |
| `limit` | query | `integer` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/audit/export

**Export Audit**

Stream ALL matching audit rows as newline-delimited JSON (oldest first), paged internally
so a large export never buffers the whole table (finding g).

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | query | `object` | No |  |
| `action` | query | `object` | No |  |
| `actor` | query | `object` | No |  |
| `start` | query | `object` | No |  |
| `end` | query | `object` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/audit/metrics

**Metrics**

In-process resilience counters (swallowed-failure visibility).

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |

---

### `POST` /v1/hooks/{key}

**Inbound Webhook**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `key` | path | `string` | Yes |  |
| `wait` | query | `boolean` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects

**List Projects**

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `ProjectOut` |

---

### `POST` /v1/projects

**Create Project**

#### Request Body (`application/json`)

Schema: `ProjectCreate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: `ProjectOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}

**Get Project**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ProjectOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PATCH` /v1/projects/{project_id}

**Update Project**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ProjectUpdate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ProjectOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/counts

**Project Counts**

Lightweight per-resource counts for the project sidebar badges
({workflows, agents, tools, components, knowledge, auth}).

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ProjectCountsOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/datasets

**List Datasets**

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

### `POST` /v1/projects/{project_id}/datasets

**Create Dataset**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `DatasetIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `DELETE` /v1/projects/{project_id}/datasets/{dataset_id}

**Delete Dataset**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `dataset_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PATCH` /v1/projects/{project_id}/datasets/{dataset_id}

**Update Dataset**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `dataset_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `DatasetIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/datasets/{dataset_id}/run

**Run Dataset**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `dataset_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `object`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/datasets/{dataset_id}/run/stream

**Run Dataset Stream**

Same as /run, but streams SSE frames (start / item / done / error) so the console can
render every case immediately and update each row live as its run finishes.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `dataset_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `object`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/datasets/{dataset_id}/runs

**List Eval Runs**

Persisted eval-run history for a dataset (newest first) - quality trend + regression view.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `dataset_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/datasets/{dataset_id}/runs/{eval_run_id}/results

**List Eval Results**

Per-item outcomes for one persisted eval run (for per-example diffing).

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `dataset_id` | path | `string` | Yes |  |
| `eval_run_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/handoffs

**List Handoffs**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `status` | query | `string` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/handoffs/{handoff_id}/reply

**Reply Handoff**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `handoff_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ReplyIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/secrets

**List Secrets**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `SecretOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/secrets

**Create Secret**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `SecretCreate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: `SecretOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `DELETE` /v1/projects/{project_id}/secrets/{name}

**Delete Secret**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `name` | path | `string` | Yes |  |
| `force` | query | `boolean` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `204` | Successful Response | None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/secrets/{name}/usage

**Secret Usage**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `name` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/traces

**List Traces**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `TraceOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/traces/{trace_id}

**Get Trace**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `trace_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `TraceDetailOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/stats/dashboard

**Dashboard**

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `DashboardStatsOut` |

---

### `GET` /v1/stats/projects/{project_id}

**Project Stats**

Project-scoped rollups + report rows (per workflow + Forge Assistant).

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ProjectStatsOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/stats/projects/{project_id}/analytics

**Project Analytics**

Time-series + breakdowns for the project Analytics dashboard, over the last `days`.

Everything is a grouped SQL aggregate (daily buckets, per-source, per-workflow, and
per-tool/per-model spans) so a dashboard load returns a bounded number of rows no matter
how large the trace history is. The previous equal-length window is rolled up too, so the
UI can show period-over-period deltas on each KPI.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `days` | query | `integer` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `AnalyticsOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/team/members

**List Members**

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |

---

### `POST` /v1/team/members

**Invite Member**

#### Request Body (`application/json`)

Schema: `InviteIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `DELETE` /v1/team/members/{user_id}

**Deactivate Member**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `user_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PATCH` /v1/team/members/{user_id}

**Update Member**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `user_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `MemberPatch`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/versions/project/{project_id}/activity

**Project Activity**

Read-only project-wide activity feed for knowledge sources + Q&A pairs (added / changed /
removed), newest first. Powers the Knowledge screen's History button.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `ActivityOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/versions/project/{project_id}/config-history

**Project Config History**

Full project snapshots (newest first, incl. the snapshot body) so the Settings > History
screen can diff consecutive versions field-by-field per section. Read-only.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `VersionDetailOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/versions/{entity_type}/{entity_id}

**List Versions**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `entity_type` | path | `string` | Yes |  |
| `entity_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `VersionOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/versions/{entity_type}/{entity_id}/restore

**Restore Version**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `entity_type` | path | `string` | Yes |  |
| `entity_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `RestoreIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `VersionDetailOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/versions/{entity_type}/{entity_id}/{version_no}

**Get Version**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `entity_type` | path | `string` | Yes |  |
| `entity_id` | path | `string` | Yes |  |
| `version_no` | path | `integer` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `VersionDetailOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/workspace

**Get Workspace**

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |

---

### `PATCH` /v1/workspace

**Update Workspace**

Owner-only: rename, change plan, or adjust quota limits (finding k).

#### Request Body (`application/json`)

Schema: `WorkspaceUpdateIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /version

**Version Info**

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `object` |

---
