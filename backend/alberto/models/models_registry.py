"""Domain ORM models."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from alberto.db.base import Base, PkTimestamp


class ModelServer(PkTimestamp, Base):
    """Configured inference endpoint or cloud provider (Alberto model registry)."""

    __tablename__ = "model_servers"
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(120))
    provider_type: Mapped[str] = mapped_column(String(40))  # ollama | lm_studio | vllm | openai_compatible | openai | anthropic | google | groq | deepseek | mistral
    base_url: Mapped[str] = mapped_column(String(500))
    api_key_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class RegisteredModel(PkTimestamp, Base):
    """Explicitly registered model instance bound to a ModelServer with tuned parameters."""

    __tablename__ = "registered_models"
    __table_args__ = (UniqueConstraint("tenant_id", "server_id", "model_name", name="uq_registered_model_tenant_server_name"),)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    server_id: Mapped[str] = mapped_column(String(36), ForeignKey("model_servers.id"), index=True)
    model_name: Mapped[str] = mapped_column(String(200))  # wire identifier sent to endpoint
    display_name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    context_window_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_window_configured: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supports_tools: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # None = unknown
    supports_vision: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # None = unknown
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    top_p: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
