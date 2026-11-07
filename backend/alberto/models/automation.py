"""Domain ORM models."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from alberto.db.base import Base, PkTimestamp

class AutomationSession(PkTimestamp, Base):
    """Persistent conversational workflow authoring session."""

    __tablename__ = "automation_sessions"
    __table_args__ = (
        Index("ix_auto_sessions_tenant_project", "tenant_id", "project_id"),
        Index("ix_auto_sessions_status", "status"),
    )

    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(255), default="New Automation")
    requirements: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(50), default="drafting")  # drafting | clarifying | ready_for_approval | approved | discarded
    strategy: Mapped[str] = mapped_column(String(50), default="single_agent")  # deterministic | single_agent | multi_agent | hybrid

    # Persistent conversational authoring state
    clarification_turns: Mapped[list] = mapped_column(JSON, default=list)
    current_proposal: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    validation_results: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    @property
    def requirement(self) -> str:
        return self.requirements

    @requirement.setter
    def requirement(self, val: str) -> None:
        self.requirements = val

    @property
    def clarifications(self) -> list:
        return self.clarification_turns or []

    @clarifications.setter
    def clarifications(self, val: list) -> None:
        self.clarification_turns = val

    @property
    def proposal(self) -> dict | None:
        return self.current_proposal

    @proposal.setter
    def proposal(self, val: dict | None) -> None:
        self.current_proposal = val

    @property
    def proposed_agents(self) -> list:
        return (self.current_proposal or {}).get("proposed_agents", [])

    @proposed_agents.setter
    def proposed_agents(self, val: list) -> None:
        p = dict(self.current_proposal or {})
        p["proposed_agents"] = val
        self.current_proposal = p

    @property
    def validation_status(self) -> str:
        return (self.validation_results or {}).get("status", "pending")

    @validation_status.setter
    def validation_status(self, val: str) -> None:
        vr = dict(self.validation_results or {})
        vr["status"] = val
        self.validation_results = vr

    @property
    def validation_errors(self) -> list:
        return (self.validation_results or {}).get("errors", [])

    @validation_errors.setter
    def validation_errors(self, val: list) -> None:
        vr = dict(self.validation_results or {})
        vr["errors"] = val
        self.validation_results = vr

    @property
    def current_plan(self) -> dict | None:
        return (self.metadata_json or {}).get("current_plan")

    @current_plan.setter
    def current_plan(self, val: dict | None) -> None:
        mj = dict(self.metadata_json or {})
        mj["current_plan"] = val
        self.metadata_json = mj


class WorkflowRepairAttempt(PkTimestamp, Base):
    """Durable tracking of autonomous failure repair attempts to prevent loops across restarts."""

    __tablename__ = "workflow_repair_attempts"
    __table_args__ = (
        Index("ix_repair_attempts_wf_fingerprint", "workflow_id", "failure_fingerprint", "workflow_revision"),
    )

    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    workflow_id: Mapped[str] = mapped_column(String(36), index=True)
    workflow_revision: Mapped[int] = mapped_column(Integer, default=1)
    failure_fingerprint: Mapped[str] = mapped_column(String(128), index=True)
    source_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1)
    repair_status: Mapped[str] = mapped_column(String(50), default="attempted")  # attempted | repaired | blocked | failed
    last_attempt_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    repair_outcome: Mapped[dict] = mapped_column(JSON, default=dict)
