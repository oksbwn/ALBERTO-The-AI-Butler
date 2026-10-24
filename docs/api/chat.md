# Assistant & Conversation API

Endpoints for interactive Butler sessions, streaming responses, and conversation threads.

> [!NOTE]
> Total verified endpoints documented: **6**.

### `POST` /v1/projects/{project_id}/assistant/resume

**Assistant Resume**

Resume a paused assistant thread (HITL approval for destructive tools).

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `AssistantResumeIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/assistant/stream

**Assistant Stream**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `AssistantIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/conversations

**List Conversations**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `actor` | query | `object` | No | Filter by user name (e.g. 'System', 'Unknown user') |
| `source` | query | `object` | No | Filter by origin (playground|api|embed|channel_*|…) |
| `status` | query | `object` | No | 'error' or 'success'/'done' |
| `search` | query | `object` | No | Match user/AI message text (any turn) |
| `limit` | query | `integer` | No |  |
| `offset` | query | `integer` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `ConversationOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/conversations/facets

**Conversation Facets**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `FacetsOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/conversations/purge

**Purge Conversations**

Manual retention control (admin only). Nothing is auto-deleted.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `older_than_days` | query | `integer` | Yes | Delete traces + spans older than this many days |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/conversations/{thread_id}

**Get Conversation**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `thread_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ConversationDetailOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---
