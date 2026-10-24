"""ORM models."""

from alberto.models.entities import (
    Agent,
    AuditLog,
    AuthProvider,
    AutomationSession,
    Channel,
    ChannelEvent,
    ChannelIdentity,
    ChannelPairing,
    Component,
    ConnectorInstall,
    Dataset,
    EntityVersion,
    HandoffRequest,
    KbSource,
    McpClient,
    Memory,
    MemoryLearningEvent,
    ModelServer,
    OAuthClient,
    OntologyEntityMapping,
    OntologyEntityType,
    OntologyRelationshipType,
    Project,
    QaPair,
    RegisteredModel,
    Run,
    Secret,
    Span,
    Tenant,
    Thread,
    Tool,
    ToolAnalysisJob,
    ToolApprovalRequest,
    ToolSet,
    ToolSetMember,
    Trace,
    Trigger,
    User,
    Workflow,
    WorkflowRepairAttempt,
)

# Eval history tables live in a separate module (append-isolated from entities.py); imported
# here so they register on Base.metadata for create_all (finding F2).
from alberto.models.evals import EvalResult, EvalRun

# Backwards-compatible alias for connector installation
ConnectorInstallation = ConnectorInstall

__all__ = [
    "Tenant", "User", "Project", "Workflow", "Thread", "Run", "Trace", "Span",
    "Tool", "ToolSet", "ToolSetMember", "AuthProvider", "Secret", "McpClient", "Agent", "KbSource", "QaPair",
    "AuditLog", "Trigger", "Channel", "Component", "HandoffRequest", "Dataset", "Memory", "MemoryLearningEvent",
    "OntologyEntityType", "OntologyRelationshipType", "OntologyEntityMapping",
    "EntityVersion", "EvalRun", "EvalResult", "OAuthClient", "ConnectorInstall", "ConnectorInstallation",
    "ModelServer", "RegisteredModel", "ToolApprovalRequest", "ToolAnalysisJob",
    "ChannelIdentity", "ChannelPairing", "ChannelEvent", "AutomationSession", "WorkflowRepairAttempt",
]

