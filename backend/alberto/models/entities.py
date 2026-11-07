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

from alberto.models.identity import (
    Tenant,
    User,
    ApiKey,
    ProjectMember,
    UserSecurity,
)
from alberto.models.workflows import (
    Project,
    Workflow,
    Component,
    Agent,
    Trigger,
    HandoffRequest,
    Dataset,
    EntityVersion,
)
from alberto.models.tools import (
    Tool,
    ToolSet,
    ToolSetMember,
    AuthProvider,
    Secret,
    McpClient,
    OAuthClient,
    ConnectorInstall,
    ToolApprovalRequest,
    ToolAnalysisJob,
)
from alberto.models.execution import (
    Thread,
    Run,
    Trace,
    AuditLog,
    Span,
)
from alberto.models.memory import (
    KbSource,
    QaPair,
    Memory,
    MemoryLearningEvent,
    OntologyEntityType,
    OntologyRelationshipType,
    OntologyEntityMapping,
)
from alberto.models.channels import (
    Channel,
    ChannelIdentity,
    ChannelPairing,
    ChannelEvent,
)
from alberto.models.models_registry import (
    ModelServer,
    RegisteredModel,
)
from alberto.models.automation import (
    AutomationSession,
    WorkflowRepairAttempt,
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
