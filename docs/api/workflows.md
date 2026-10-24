# Automate & Workflows API

Endpoints for visual canvas workflows, step execution, triggers, and runs.

> [!NOTE]
> Total verified endpoints documented: **51**.

### `GET` /api/projects/{project_id}/automate/capabilities

**Discover Capabilities**

Discover permitted platform capabilities within current project/user scope.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `CapabilityDiscoveryResult` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /api/projects/{project_id}/automate/monitoring

**Get Monitoring Summary**

Retrieve grounded execution metrics, run counts, active triggers, and slowest node.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `workflow_id` | query | `object` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `WorkflowMonitoringReport` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /api/projects/{project_id}/automate/runs/{run_id}/diagnose

**Diagnose Run Failure**

Inspect execution traces, identify root cause, and formulate safe repair recommendations.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `run_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `WorkflowExecutionDiagnostic` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /api/projects/{project_id}/automate/sessions

**List Authoring Sessions**

List all authoring sessions for this project.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `AuthoringSessionOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /api/projects/{project_id}/automate/sessions

**Create Authoring Session**

Start a new persistent conversational authoring session.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `AuthoringSessionCreateIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: `AuthoringSessionOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /api/projects/{project_id}/automate/sessions/{session_id}

**Get Authoring Session**

Retrieve an authoring session state by ID.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `session_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `AuthoringSessionOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /api/projects/{project_id}/automate/sessions/{session_id}/approve

**Approve Session Proposal**

Consolidated approval: creates specialist agents, persists workflow and activates triggers.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `session_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ApprovalRequestIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ApprovalResultOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /api/projects/{project_id}/automate/sessions/{session_id}/messages

**Send Session Message**

Submit a requirement or clarification turn to the authoring session.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `session_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `AuthoringMessageIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `AuthoringStepResult` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /api/projects/{project_id}/automate/sessions/{session_id}/test

**Test Session Proposal**

Run an isolated safe dry-run test of the proposed workflow without live side effects.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `session_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `SafeTestResult` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /api/projects/{project_id}/automate/sessions/{session_id}/validate

**Validate Session Proposal**

Deterministic validation of the current proposed workflow definition.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `session_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /api/projects/{project_id}/automate/workflows/{workflow_id}/optimise

**Get Workflow Optimisation**

Analyze workflow execution history and propose grounded optimizations.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `workflow_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `WorkflowOptimisationReport` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /api/projects/{project_id}/automate/workflows/{workflow_id}/repair

**Repair Workflow**

Safely apply non-behavioral configuration self-repairs, rejecting unauthorized privilege expansions.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `workflow_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/automate/capabilities

**Discover Capabilities**

Discover permitted platform capabilities within current project/user scope.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `CapabilityDiscoveryResult` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/automate/monitoring

**Get Monitoring Summary**

Retrieve grounded execution metrics, run counts, active triggers, and slowest node.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `workflow_id` | query | `object` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `WorkflowMonitoringReport` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/automate/runs/{run_id}/diagnose

**Diagnose Run Failure**

Inspect execution traces, identify root cause, and formulate safe repair recommendations.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `run_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `WorkflowExecutionDiagnostic` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/automate/sessions

**List Authoring Sessions**

List all authoring sessions for this project.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `AuthoringSessionOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/automate/sessions

**Create Authoring Session**

Start a new persistent conversational authoring session.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `AuthoringSessionCreateIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: `AuthoringSessionOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/automate/sessions/{session_id}

**Get Authoring Session**

Retrieve an authoring session state by ID.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `session_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `AuthoringSessionOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/automate/sessions/{session_id}/approve

**Approve Session Proposal**

Consolidated approval: creates specialist agents, persists workflow and activates triggers.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `session_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ApprovalRequestIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ApprovalResultOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/automate/sessions/{session_id}/messages

**Send Session Message**

Submit a requirement or clarification turn to the authoring session.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `session_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `AuthoringMessageIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `AuthoringStepResult` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/automate/sessions/{session_id}/test

**Test Session Proposal**

Run an isolated safe dry-run test of the proposed workflow without live side effects.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `session_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `SafeTestResult` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/automate/sessions/{session_id}/validate

**Validate Session Proposal**

Deterministic validation of the current proposed workflow definition.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `session_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/automate/workflows/{workflow_id}/optimise

**Get Workflow Optimisation**

Analyze workflow execution history and propose grounded optimizations.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `workflow_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `WorkflowOptimisationReport` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/automate/workflows/{workflow_id}/repair

**Repair Workflow**

Safely apply non-behavioral configuration self-repairs, rejecting unauthorized privilege expansions.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `workflow_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/components

**List Components**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `ComponentOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/components

**Create Component**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ComponentCreate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: `ComponentOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/components/export

**Export Components**

Serialize the selected components (HTML/CSS/props/actions) into a downloadable bundle.

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

### `POST` /v1/projects/{project_id}/components/import

**Import Components**

Create components from an uploaded bundle in THIS project (auto-renamed on collision).

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

### `DELETE` /v1/projects/{project_id}/components/{component_id}

**Delete Component**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `component_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `204` | Successful Response | None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/components/{component_id}

**Get Component**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `component_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ComponentOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PATCH` /v1/projects/{project_id}/components/{component_id}

**Update Component**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `component_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ComponentUpdate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ComponentOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/run

**Project Run**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `Idempotency-Key` | header | `object` | No |  |

#### Request Body (`application/json`)

Schema: `ProjectRunIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/triggers

**List Triggers**

Project triggers, plus your own personal ones.

Someone else's personal trigger is hidden - a colleague's private lead-chaser is noise on
your screen. It is NOT hidden from an admin, though: every run it produces is already in
Traces, so filtering it out of the one screen that explains WHY those runs happen would be
false privacy that only costs the person who has to answer for the project.

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

### `PUT` /v1/projects/{project_id}/triggers/{trigger_id}/run-as

**Set Run As**

Point this trigger at a person's connected accounts.

Claiming it for YOURSELF is open to any real logged-in user - it only ever narrows the run to
accounts you personally connected. Assigning it to SOMEONE ELSE means their credentials get
used by a workflow they may not have touched, so that is an editor decision.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `trigger_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `object`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PUT` /v1/projects/{project_id}/triggers/{trigger_id}/scope

**Set Scope**

Move a trigger between "the team's" and "mine".

Sharing it with the project is an editor decision: colleagues will see it, depend on it, and
be able to reassign it. Making one personal is open to the person it runs as - it is their
account doing the work - but not to a bystander, because hiding a trigger others rely on
would look exactly like it disappearing.

Making one personal is deliberately NOT an ordinary editor power. "Personal" means "listed
only for the person it runs as", so an editor doing it to a trigger that runs as someone else
- or as nobody - removes it from their own screen the instant they click, with no control
left to put it back. Only the person it runs as, or an admin (who keeps oversight visibility
either way), can take that step.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `trigger_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ScopeIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/workflows

**List Workflows**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: list of `WorkflowOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/workflows

**Create Workflow**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `WorkflowCreate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: `WorkflowOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/workflows/export

**Export Workflows**

Serialize the selected workflows (canvas + executable) into a downloadable bundle.

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

### `POST` /v1/projects/{project_id}/workflows/import

**Import Workflows**

Create workflows from an uploaded bundle in THIS project (imported as drafts).

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

### `POST` /v1/projects/{project_id}/workflows/validate

**Validate Executable**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ExecutableIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ValidateOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `DELETE` /v1/projects/{project_id}/workflows/{workflow_id}

**Delete Workflow**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `workflow_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `204` | Successful Response | None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/workflows/{workflow_id}

**Get Workflow**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `workflow_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `WorkflowOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PATCH` /v1/projects/{project_id}/workflows/{workflow_id}

**Update Workflow**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `workflow_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `WorkflowUpdate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `WorkflowOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PUT` /v1/projects/{project_id}/workflows/{workflow_id}/canvas

**Save Canvas**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `workflow_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `CanvasSaveIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ValidateOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `PUT` /v1/projects/{project_id}/workflows/{workflow_id}/executable

**Update Executable**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `workflow_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ExecutableIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `ValidateOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/workflows/{workflow_id}/publish

**Publish Workflow**

Validate the stored executable and mark the workflow active (a published version).

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `workflow_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: `WorkflowOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/workflows/{workflow_id}/runs

**Create Run**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `workflow_id` | path | `string` | Yes |  |
| `Idempotency-Key` | header | `object` | No |  |

#### Request Body (`application/json`)

Schema: `RunCreate`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: `RunOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/workflows/{workflow_id}/runs/{run_id}/cancel

**Cancel Run**

Cancel a run: mark it canceled and cooperatively stop it (frees the tenant-concurrency
slot). A terminal run (done/error/canceled) returns ok=False with its current status.

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `workflow_id` | path | `string` | Yes |  |
| `run_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/workflows/{workflow_id}/runs/{run_id}/rerun

**Rerun**

Replay a past run: create a new run with the same input (fresh thread).

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `workflow_id` | path | `string` | Yes |  |
| `run_id` | path | `string` | Yes |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `201` | Successful Response | `application/json`: `RunOut` |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `POST` /v1/projects/{project_id}/workflows/{workflow_id}/runs/{run_id}/resume

**Resume Run**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `workflow_id` | path | `string` | Yes |  |
| `run_id` | path | `string` | Yes |  |

#### Request Body (`application/json`)

Schema: `ResumeIn`

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---

### `GET` /v1/projects/{project_id}/workflows/{workflow_id}/runs/{run_id}/stream

**Stream Run**

#### Parameters

| Name | In | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `project_id` | path | `string` | Yes |  |
| `workflow_id` | path | `string` | Yes |  |
| `run_id` | path | `string` | Yes |  |
| `Last-Event-ID` | header | `object` | No |  |

#### Responses

| Status | Description | Schema |
| :--- | :--- | :--- |
| `200` | Successful Response | `application/json`: None |
| `422` | Validation Error | `application/json`: `HTTPValidationError` |

---
