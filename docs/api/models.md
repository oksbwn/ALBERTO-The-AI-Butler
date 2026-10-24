# Model Catalog & Providers API

Endpoints for discovered LLMs, provider registrations, pricing, and active assignments.

> [!NOTE]
> Total verified endpoints documented: **18**.

### `GET` /v1/models

**List Models**

Unified Model Catalog. Chat list contains ONLY explicitly registered models.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | query | `object` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `UnifiedCatalogOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PUT` /v1/models/default

**Set Default Model**

#### Request Body (`application/json`)

Schema: `SetDefaultModelIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `object` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/models/discover

**Legacy Discover**

#### Request Body (`application/json`)

Schema: `ServerTestIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `object` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/models/embeddings/download

**Download Embedding Model**

Download ONNX weights for ONLY the selected model into data/models/fastembed.

#### Request Body (`application/json`)

Schema: `EmbeddingModelDownloadIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `object` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/models/embeddings/status

**Get Embedding Model Status**

Check if model weights exist in data/models/fastembed for the selected embedding model.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `model_id` | query | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `EmbeddingModelStatusOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/models/registry

**List Registered Models**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | query | `object` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `RegisteredModelOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/models/registry

**Register Model**

#### Request Body (`application/json`)

Schema: `RegisteredModelCreate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: `RegisteredModelOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `DELETE` /v1/models/registry/{model_id}

**Delete Registered Model**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `model_id` | path | `string` | Yes |  |
| `force` | query | `boolean` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `204` | Successful Response | None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PATCH` /v1/models/registry/{model_id}

**Update Registered Model**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `model_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `RegisteredModelUpdate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `RegisteredModelOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/models/registry/{model_id}/test-inference

**Test Model Inference**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `model_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `TestInferenceIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `TestInferenceOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/models/registry/{model_id}/test-tools

**Test Model Tool Calling**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `model_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `TestToolsOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/models/servers

**List Servers**

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `ModelServerOut` |

---

### `POST` /v1/models/servers

**Create Server**

#### Request Body (`application/json`)

Schema: `ModelServerCreate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: `ModelServerOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/models/servers/test

**Test Server Connectivity**

#### Request Body (`application/json`)

Schema: `ServerTestIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ServerTestOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `DELETE` /v1/models/servers/{server_id}

**Delete Server**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `server_id` | path | `string` | Yes |  |
| `force` | query | `boolean` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `204` | Successful Response | None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PATCH` /v1/models/servers/{server_id}

**Update Server**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `server_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ModelServerUpdate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ModelServerOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/models/servers/{server_id}/discover

**Discover Server Models**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `server_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ServerDiscoverOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/node-types

**List Node Types**

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `NodeTypeOut` |

---
