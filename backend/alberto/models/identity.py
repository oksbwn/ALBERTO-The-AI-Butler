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

class Tenant(PkTimestamp, Base):
    __tablename__ = "tenants"
    name: Mapped[str] = mapped_column(String(200))
    plan: Mapped[str] = mapped_column(String(50), default="free")
    region: Mapped[str | None] = mapped_column(String(50), nullable=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)


class User(PkTimestamp, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(30), default="owner")  # owner|admin|editor|viewer|connector
    status: Mapped[str] = mapped_column(String(20), default="active")
    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True)


class ApiKey(PkTimestamp, Base):
    """A hashed, revocable API key for server-to-server callers (finding h). Scoped to a tenant
    with a fixed role; the plaintext is shown ONCE at creation and only its SHA-256 hash is
    stored. Presented as `Authorization: Bearer <key>` and resolved in get_current_user. This
    is per-tenant and per-role, unlike the single static FORGE_SERVICE_API_TOKEN."""

    __tablename__ = "api_keys"
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(120))
    # Non-secret lookup hint (the key's leading chars), safe to display in the console.
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # sha256 hex of the full key
    role: Mapped[str] = mapped_column(String(30), default="editor")  # owner|admin|editor|viewer
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|revoked
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)  # optional hard expiry
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Legacy fields retained for database schema compatibility with existing migrations:
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class ProjectMember(PkTimestamp, Base):
    """Per-project role grant (finding h). Present => the member's EFFECTIVE role on that project
    is the higher of this and their tenant-wide role; absent => the tenant-wide role applies, so
    this is purely additive and backward-compatible."""

    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    role: Mapped[str] = mapped_column(String(30), default="viewer")  # owner|admin|editor|viewer


class UserSecurity(PkTimestamp, Base):
    """Per-user auth state kept OFF the `users` row (finding j) so it can be added without an
    ALTER of an existing table: email-verification flag + optional TOTP MFA. NOTE: `totp_secret`
    is stored as a base32 string; encrypt it at rest (secret store / KMS) before enabling MFA on
    a shared production install."""

    __tablename__ = "user_security"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_security_user"),)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
