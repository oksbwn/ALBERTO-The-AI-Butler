"""Automation Manager Pydantic schemas and contracts.

Defines validated data structures for:
- Capability discovery
- Specialist agent proposals
- Workflow planning and low-code designer proposals
- Conversational authoring sessions and messages
- Graph validation reports
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

PlanningStrategy = Literal["deterministic", "single_agent", "multi_agent", "hybrid"]


class DiscoveredWorkflow(BaseModel):
    id: str
    name: str
    description: str | None = None
    status: str = "draft"
    node_count: int = 0


class DiscoveredAgent(BaseModel):
    id: str
    name: str
    description: str | None = None
    system_key: str | None = None
    is_system: bool = False
    model: str | None = None
    tools: list[str] = Field(default_factory=list)


class DiscoveredNode(BaseModel):
    type: str
    category: str = "flow"
    label: str = ""
    description: str = ""
    allows_cycle: bool = False
    input_ports: list[dict[str, Any]] = Field(default_factory=list)
    output_ports: list[dict[str, Any]] = Field(default_factory=list)


class DiscoveredTool(BaseModel):
    id: str
    name: str
    description: str | None = None
    kind: str = "builtin"
    effect_type: str = "unknown"
    risk_level: str = "medium"
    requires_approval: bool = False
    read_only: bool = False


class DiscoveredToolSet(BaseModel):
    id: str
    name: str
    description: str | None = None
    tool_ids: list[str] = Field(default_factory=list)


class DiscoveredIntegration(BaseModel):
    name: str
    type: Literal["mcp", "connector"]
    status: str = "enabled"
    detail: str = ""


class DiscoveredChannel(BaseModel):
    name: str
    type: str
    enabled: bool = True


class DiscoveredModelInfo(BaseModel):
    default_model: str = ""
    registered_models: list[str] = Field(default_factory=list)
    servers: list[str] = Field(default_factory=list)


class CapabilityDiscoveryResult(BaseModel):
    """Platform capabilities discovered for the current user and project scope."""
    project_id: str
    workflows: list[DiscoveredWorkflow] = Field(default_factory=list)
    specialist_agents: list[DiscoveredAgent] = Field(default_factory=list)
    system_agents: list[DiscoveredAgent] = Field(default_factory=list)
    node_catalog: list[DiscoveredNode] = Field(default_factory=list)
    tools: list[DiscoveredTool] = Field(default_factory=list)
    tool_sets: list[DiscoveredToolSet] = Field(default_factory=list)
    integrations: list[DiscoveredIntegration] = Field(default_factory=list)
    channels: list[DiscoveredChannel] = Field(default_factory=list)
    models: DiscoveredModelInfo = Field(default_factory=DiscoveredModelInfo)
    validation_layers: list[str] = Field(
        default_factory=lambda: [
            "shape_and_contracts",
            "node_config_schemas",
            "port_io_compatibility",
            "connectivity_and_cycle_rules",
            "state_schema_declarations",
        ]
    )


class AgentProposal(BaseModel):
    """Structured proposal for a new specialist agent (not immediately created)."""
    name: str
    responsibility: str
    system_prompt: str
    model: str | None = None
    tools: list[str] = Field(default_factory=list)
    tool_sets: list[str] = Field(default_factory=list)
    input_contract: str | None = None
    output_contract: str | None = None
    tool_permissions: list[str] = Field(default_factory=list)
    risk_info: dict[str, Any] = Field(default_factory=dict)
    intended_workflow_association: str | None = None


class WorkflowProposal(BaseModel):
    """Workflow proposal fully compatible with Alberto's low-code designer & compiler."""
    title: str
    strategy: PlanningStrategy = "single_agent"
    description: str = ""
    executable: dict[str, Any]
    canvas: dict[str, Any]
    proposed_agents: list[AgentProposal] = Field(default_factory=list)
    reused_agents: list[str] = Field(default_factory=list)
    reused_tools: list[str] = Field(default_factory=list)
    explanation: str = ""
    validation: dict[str, Any] = Field(default_factory=dict)
    workflow_id: str | None = None
    base_workflow_revision: int | None = None
    content_fingerprint: str | None = None
    safe_test_results: Any = None


class AuthoringSessionCreateIn(BaseModel):
    requirement: str
    title: str | None = None


class AuthoringMessageIn(BaseModel):
    message: str
    expected_revision: int | None = None


class AuthoringSessionOut(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    user_id: str | None = None
    title: str
    requirement: str
    status: str
    clarifications: list[dict[str, Any]] = Field(default_factory=list)
    current_plan: dict[str, Any] | None = None
    proposal: dict[str, Any] | None = None
    proposed_agents: list[dict[str, Any]] = Field(default_factory=list)
    validation_status: str = "pending"
    validation_errors: list[dict[str, Any]] = Field(default_factory=list)
    revision: int = 1
    created_at: datetime
    updated_at: datetime


class AuthoringStepResult(BaseModel):
    action: Literal["clarify", "plan", "error"]
    session_id: str
    revision: int
    questions: list[str] = Field(default_factory=list)
    proposal: WorkflowProposal | None = None
    validation_status: str = "pending"
    validation_errors: list[dict[str, Any]] = Field(default_factory=list)
    error_message: str | None = None


class SafeTestCheck(BaseModel):
    name: str
    status: Literal["passed", "failed", "warning"]
    detail: str = ""


class SafeTestResult(BaseModel):
    session_id: str
    valid: bool
    status: Literal["passed", "failed", "warning"]
    checks: list[SafeTestCheck] = Field(default_factory=list)
    risks_identified: list[str] = Field(default_factory=list)
    side_effects: list[str] = Field(default_factory=list)
    tested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ApprovalRequestIn(BaseModel):
    revision: int
    create_agents: bool = True
    activate: bool = True
    notes: str | None = None


class ApprovalResultOut(BaseModel):
    session_id: str
    status: str
    revision: int
    workflow_id: str
    workflow_name: str
    created_agent_ids: list[str] = Field(default_factory=list)
    activated: bool
    approved_by: str | None = None
    message: str = ""


class WorkflowExecutionDiagnostic(BaseModel):
    run_id: str
    workflow_id: str
    workflow_name: str
    status: str
    error: str | None = None
    category: str
    longest_step: dict[str, Any] | None = None
    root_cause: str
    trace_references: list[str] = Field(default_factory=list)
    proposed_repair: str | None = None
    requires_approval: bool = False


class WorkflowMonitoringReport(BaseModel):
    workflow_id: str | None = None
    workflow_name: str | None = None
    active_runs: int = 0
    total_runs: int = 0
    success_rate: float = 0.0
    last_run: dict[str, Any] | None = None
    slowest_step: dict[str, Any] | None = None
    triggers: list[dict[str, Any]] = Field(default_factory=list)


class WorkflowOptimisationReport(BaseModel):
    workflow_id: str
    workflow_name: str
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    potential_token_savings: int = 0
    potential_latency_reduction_ms: int = 0
