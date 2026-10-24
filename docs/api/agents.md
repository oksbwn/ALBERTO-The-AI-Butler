# Agents & Specialists API

Endpoints for defining, inspecting, updating, and delegating to specialist agent configurations.

> [!NOTE]
> Total verified endpoints documented: **8**.

### `GET` /v1/projects/{project_id}/agents

**List Agents**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `AgentOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/agents

**Create Agent**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `AgentCreate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: `AgentOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/agents/export

**Export Agents**

Serialize the selected agent presets (full config) into a downloadable bundle.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ExportIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/agents/import

**Import Agents**

Create agent presets from an uploaded bundle in THIS project (auto-renamed on collision).

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ImportIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ImportReport` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/agents/validate

**Validate Agent**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `AgentCreate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ValidateOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `DELETE` /v1/projects/{project_id}/agents/{agent_id}

**Delete Agent**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `agent_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `204` | Successful Response | None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/agents/{agent_id}

**Get Agent**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `agent_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `AgentOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PATCH` /v1/projects/{project_id}/agents/{agent_id}

**Update Agent**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `agent_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `AgentUpdate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `AgentOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---
