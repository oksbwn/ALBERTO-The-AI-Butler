# Tools & Integrations API

Endpoints for Tool Manager, MCP clients, REST connectors, and channel bindings.

> [!NOTE]
> Total verified endpoints documented: **67**.

### `POST` /v1/channels/email/{key}/inbound

**Email Inbound**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `key` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/channels/telegram/{key}/webhook

**Telegram Webhook**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `key` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/channels

**List Channels**

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

### `POST` /v1/projects/{project_id}/channels

**Create Channel**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ChannelIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `DELETE` /v1/projects/{project_id}/channels/{channel_id}

**Delete Channel**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `channel_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PATCH` /v1/projects/{project_id}/channels/{channel_id}

**Update Channel**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `channel_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ChannelPatch`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/channels/{channel_id}/diagnostics

**Channel Diagnostics**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `channel_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/channels/{channel_id}/events

**List Events**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `channel_id` | path | `string` | Yes |  |
| `limit` | query | `integer` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/channels/{channel_id}/identities

**List Identities**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `channel_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `DELETE` /v1/projects/{project_id}/channels/{channel_id}/identities/{identity_id}

**Revoke Identity**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `channel_id` | path | `string` | Yes |  |
| `identity_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/channels/{channel_id}/pairings/confirm

**Confirm Pairing**

The authenticated Alberto user proves they own the external account by entering the
one-time code that account received. Binds to the caller (admins may bind another user).

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `channel_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `PairConfirmIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/channels/{channel_id}/send

**Send Via Channel**

Authorised outbound message to a VERIFIED paired identity. Not an open relay: the
recipient is an identity id, the actor's authority is derived from the authenticated user.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `channel_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `SendIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/channels/{channel_id}/test

**Test Channel**

Connection test (no message is sent to anyone).

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `channel_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/connections

**List My Connections**

The per-user providers this project defines, each with whether the CALLER has connected it.
Minimal fields only (no config / secret refs) — safe for the connector home page.

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

### `DELETE` /v1/projects/{project_id}/connections/{ap_id}

**Clear My Connection**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `ap_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `204` | Successful Response | None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/connections/{ap_id}

**My Connection Status**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `ap_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PUT` /v1/projects/{project_id}/connections/{ap_id}

**Set My Connection**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `ap_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `UserConnectionIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `204` | Successful Response | None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/connectors

**List Installed**

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

### `GET` /v1/projects/{project_id}/connectors/catalog

**List Catalog**

The bundled catalog, each entry flagged with whether this project already has it.

Reads a directory of JSON files - no network call, no third-party service, no API key. This
route works identically on an air-gapped install. Whether an entry is CONNECTABLE is read
from the deployment's environment, which is also free: no per-connector secret lookups just
to paint a page.

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

### `GET` /v1/projects/{project_id}/connectors/catalog/{slug}

**Get Catalog Entry**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `slug` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/connectors/custom

**Install Custom**

Install a manifest the user supplied. Same validator, same install path, same rows -
a custom connector is not a second-class citizen, it just isn't in the bundled catalog.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `CustomInstallIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/connectors/examples

**List Examples**

Ready-made manifests for services that CAN'T be one-click: an API key, a bot token or a
per-tenant subdomain has to come from somewhere, and that somewhere is a person typing it.

They are offered as starting points for the custom-connector form - open one, adjust it, add
your key - rather than sitting in the gallery pretending to be one click away.

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

### `POST` /v1/projects/{project_id}/connectors/validate

**Validate Manifest**

Dry-run a manifest so the paste-a-manifest form can show errors before anything is
created. Creates nothing and touches no credentials.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `object`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `DELETE` /v1/projects/{project_id}/connectors/{slug}

**Uninstall Connector**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `slug` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `204` | Successful Response | None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/connectors/{slug}/connect

**Connect Connector**

Begin the OAuth consent for this connector and return the URL to open.

This is the WHOLE flow from the user's side: one call, one browser round trip, connected.
If the project doesn't have the connector yet it is installed here rather than being a
separate step the person has to know about - "install" is Forge's internal bookkeeping
(create an auth provider, a tool set, a tool per action), not a decision anyone came here
to make.

For an MCP-backed connector whose manifest opted into discovery, the server's OAuth metadata
is fetched and a client is registered dynamically FIRST - that is what makes a one-click
connect possible against servers that support it, with the static manifest endpoints as the
fallback for those that don't.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `slug` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `object`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PUT` /v1/projects/{project_id}/connectors/{slug}/credentials

**Set Credentials**

Update the connector's stored setup values (rotate a client secret, fix a typo'd key).

Only keys the manifest declares are accepted; an unknown key is ignored rather than written,
so this route can never be used to plant an arbitrary secret under a connector's namespace.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `slug` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `CredentialsIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `204` | Successful Response | None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/connectors/{slug}/disconnect

**Disconnect Connector**

Revoke the stored token WITHOUT uninstalling: the tools stay wired into workflows and
agents, they just stop being able to act until reconnected. Uninstall is the destructive one.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `slug` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `object`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `204` | Successful Response | None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/connectors/{slug}/install

**Install Connector**

Add a catalog connector without connecting to it yet.

`POST /{slug}/connect` does this implicitly, which is the path the UI takes. This route is
what you want when adding the connector and signing in are done by different people - an
editor wires up the tools, and everyone else connects their own account afterwards.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `slug` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `object`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/connectors/{slug}/status

**Connector Status**

Whether this connector is usable right now - and for a per-user connector, whether the
CALLER personally has connected it (which is the only status that matters to them).

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `slug` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/connectors/{slug}/sync

**Sync Connector**

Bring a connector's actions back in line with its manifest.

Two different operations behind one button, with two different gates:

* MCP - ask the server what it exposes, using the CALLER's credential because that is the
  only one a per-user connector has. Open to anyone who can connect: gating it would leave
  whoever actually signed in staring at zero actions, and the rows created are entirely
  determined by what the vendor advertises for a connector an editor already added.
* REST - re-apply the bundled manifest over existing Tool rows. That is a project-level
  write (it rewrites tool configs everyone's workflows run), so it stays editor-gated even
  though the values are deterministic.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `slug` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/integration-manager/analyze

**Analyze Tool**

Analyze a registered or candidate tool for capability, effect, and risk classification.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `AnalyzeToolIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ToolAnalysisResult` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/integration-manager/approvals/{approval_id}

**Get Approval Request**

Retrieve an approval request state.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `approval_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/integration-manager/approvals/{approval_id}/decide

**Decide Approval Request Endpoint**

Decide a pending tool approval request (approve | reject | cancel).

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `approval_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ApprovalDecisionIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/integration-manager/diagnose

**Diagnose Tool**

Diagnose execution errors or status degradation for a tool.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `DiagnoseToolIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ToolDiagnosticReport` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/integration-manager/diagnose-channel/{channel_id}

**Diagnose Channel Endpoint**

Integration Manager diagnostic report for a channel (connectivity, webhook, pairing).

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `channel_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/integration-manager/suggest

**Suggest Tools**

Suggest registered tools suitable for a user intent.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `SuggestToolsIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `ToolMatchSuggestion` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PATCH` /v1/projects/{project_id}/integration-manager/tools/{tool_id}/activation

**Update Tool Activation**

Update activation state of a tool, enforcing policy boundaries.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `tool_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ActivationIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/mcp-clients

**List Clients**

Registered MCP servers, each flagged with the connector that owns it (if any).

A connector-owned server already surfaces its tools as a tool set, so anything picking tools
for an agent should offer the SET and skip the server - listing both makes one integration
look like two, and granting either does the same thing.

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

### `POST` /v1/projects/{project_id}/mcp-clients

**Create Client**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `McpClientIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `DELETE` /v1/projects/{project_id}/mcp-clients/{client_id}

**Delete Client**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `client_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PATCH` /v1/projects/{project_id}/mcp-clients/{client_id}

**Update Client**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `client_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `McpClientPatch`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/mcp-clients/{client_id}/capabilities

**Get Capabilities**

Retrieve cached discovery capabilities and fingerprint without triggering remote connection.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `client_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PATCH` /v1/projects/{project_id}/mcp-clients/{client_id}/learning

**Update Learning Toggle**

Toggle tool execution learning permission for this specific integration.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `client_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `McpLearningToggleIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/mcp-clients/{client_id}/refresh

**Refresh Capabilities**

Explicitly discover and refresh integration tool schemas, fingerprint, and graph representation.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `client_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/mcp-clients/{client_id}/tools

**List Remote Tools**

Connect to the server and list the tools it exposes - drives the 'pick which to add' UI.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `client_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/tool-manager/analyze

**Analyze Tool**

Analyze a registered or candidate tool for capability, effect, and risk classification.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `AnalyzeToolIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ToolAnalysisResult` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/tool-manager/approvals/{approval_id}

**Get Approval Request**

Retrieve an approval request state.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `approval_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/tool-manager/approvals/{approval_id}/decide

**Decide Approval Request Endpoint**

Decide a pending tool approval request (approve | reject | cancel).

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `approval_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ApprovalDecisionIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/tool-manager/diagnose

**Diagnose Tool**

Diagnose execution errors or status degradation for a tool.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `DiagnoseToolIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ToolDiagnosticReport` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/tool-manager/diagnose-channel/{channel_id}

**Diagnose Channel Endpoint**

Integration Manager diagnostic report for a channel (connectivity, webhook, pairing).

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `channel_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/tool-manager/suggest

**Suggest Tools**

Suggest registered tools suitable for a user intent.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `SuggestToolsIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `ToolMatchSuggestion` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PATCH` /v1/projects/{project_id}/tool-manager/tools/{tool_id}/activation

**Update Tool Activation**

Update activation state of a tool, enforcing policy boundaries.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `tool_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ActivationIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/tool-sets

**List Tool Sets**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `ToolSetOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/tool-sets

**Create Tool Set**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ToolSetCreate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: `ToolSetOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `DELETE` /v1/projects/{project_id}/tool-sets/{set_id}

**Delete Tool Set**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `set_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `204` | Successful Response | None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/tool-sets/{set_id}

**Get Tool Set**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `set_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ToolSetOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PATCH` /v1/projects/{project_id}/tool-sets/{set_id}

**Update Tool Set**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `set_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ToolSetUpdate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ToolSetOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `DELETE` /v1/projects/{project_id}/tool-sets/{set_id}/tools/{tool_id}

**Remove Tool From Set**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `set_id` | path | `string` | Yes |  |
| `tool_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `204` | Successful Response | None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/tool-sets/{set_id}/tools/{tool_id}

**Add Tool To Set**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `set_id` | path | `string` | Yes |  |
| `tool_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `204` | Successful Response | None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/tools

**List Tools**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `ToolOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/tools

**Create Tool**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ToolCreate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: `ToolOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/tools/export

**Export Tools**

Serialize the selected tools into a downloadable single-type bundle.

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

### `POST` /v1/projects/{project_id}/tools/import

**Import Tools**

Create tools from an uploaded bundle in THIS project (new ids, auto-renamed on collision).

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

### `DELETE` /v1/projects/{project_id}/tools/{tool_id}

**Delete Tool**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `tool_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `204` | Successful Response | None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/tools/{tool_id}

**Get Tool**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `tool_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ToolOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PATCH` /v1/projects/{project_id}/tools/{tool_id}

**Update Tool**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `tool_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ToolUpdate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ToolOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/tools/{tool_id}/test

**Test Tool**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `tool_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ToolTestIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---
