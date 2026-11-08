"""ORM entities - backward compatibility facade.

The ORM models have been decomposed into domain modules:
- alberto.models.identity
- alberto.models.workflows
- alberto.models.tools
- alberto.models.execution
- alberto.models.memory
- alberto.models.channels
- alberto.models.models_registry
- alberto.models.automation
"""

from __future__ import annotations

from alberto.models.automation import (
    AutomationSession,
    WorkflowRepairAttempt,
)
from alberto.models.channels import (
    Channel,
    ChannelEvent,
    ChannelIdentity,
    ChannelPairing,
)
from alberto.models.execution import (
    AuditLog,
    Run,
    Span,
    Thread,
    Trace,
)
from alberto.models.identity import (
    ApiKey,
    ProjectMember,
    Tenant,
    User,
    UserSecurity,
)
from alberto.models.memory import (
    KbSource,
    Memory,
    MemoryLearningEvent,
    OntologyEntityMapping,
    OntologyEntityType,
    OntologyRelationshipType,
    QaPair,
)
from alberto.models.models_registry import (
    ModelServer,
    RegisteredModel,
)
from alberto.models.tools import (
    AuthProvider,
    ConnectorInstall,
    McpClient,
    OAuthClient,
    Secret,
    Tool,
    ToolAnalysisJob,
    ToolApprovalRequest,
    ToolSet,
    ToolSetMember,
)
from alberto.models.workflows import (
    Agent,
    Component,
    Dataset,
    EntityVersion,
    HandoffRequest,
    Project,
    Trigger,
    Workflow,
)

__all__ = [
    "Tenant", "User", "ApiKey", "ProjectMember", "UserSecurity",
    "Project", "Workflow", "Component", "Agent", "Trigger", "HandoffRequest", "Dataset", "EntityVersion",
    "Tool", "ToolSet", "ToolSetMember", "AuthProvider", "Secret", "McpClient", "OAuthClient",
    "ConnectorInstall", "ToolApprovalRequest", "ToolAnalysisJob",
    "Thread", "Run", "Trace", "AuditLog", "Span",
    "KbSource", "QaPair", "Memory", "MemoryLearningEvent",
    "OntologyEntityType", "OntologyRelationshipType", "OntologyEntityMapping",
    "Channel", "ChannelIdentity", "ChannelPairing", "ChannelEvent",
    "ModelServer", "RegisteredModel",
    "AutomationSession", "WorkflowRepairAttempt",
]
