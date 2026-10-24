"""Tool Manager Pydantic schemas and contracts.

Defines validated data structures for:
- Tool effect and risk classification
- Capability categorization
- Analysis and activation recommendations
- Intent-based tool suggestion
- Execution failure diagnostics
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ToolEffect = Literal["read", "write", "delete", "unknown"]
ToolRiskLevel = Literal["low", "medium", "high", "critical"]
ToolActivationRecommendation = Literal["auto", "manual_review", "restricted"]


class ToolAnalysisResult(BaseModel):
    """Structured output contract for tool capability and safety analysis."""

    tool_id: str
    category: str = Field(
        default="other",
        description="Functional category (e.g. communication, productivity, smart_home, data, system, utilities)",
    )
    capabilities: list[str] = Field(
        default_factory=list,
        description="Atomic capabilities provided by this tool",
    )
    effect: ToolEffect = Field(
        default="unknown",
        description="Declared or inferred side-effect classification",
    )
    risk: ToolRiskLevel = Field(
        default="medium",
        description="Evaluated risk level based on effect and sensitive surfaces",
    )
    description: str = Field(
        default="",
        description="Refined description optimized for LLM tool selection",
    )
    similar_tool_ids: list[str] = Field(
        default_factory=list,
        description="Identified existing tools with overlapping capabilities",
    )
    recommended_activation: ToolActivationRecommendation = Field(
        default="manual_review",
        description="Recommended activation policy (auto, manual_review, or restricted)",
    )
    confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Confidence score for the analysis",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Potential safety, schema, or usability caveats",
    )


class ToolMatchSuggestion(BaseModel):
    """Candidate tool suggested for a given user intent."""

    tool_id: str
    tool_name: str
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    capabilities: list[str] = Field(default_factory=list)
    effect: ToolEffect = "unknown"
    risk: ToolRiskLevel = "medium"


class ToolDiagnosticReport(BaseModel):
    """Structured diagnostic analysis for tool execution health."""

    tool_id: str
    tool_name: str
    health_status: Literal["healthy", "degraded", "error", "unknown"] = "unknown"
    failure_count: int = 0
    root_cause_category: Literal[
        "none", "auth", "schema_mismatch", "timeout", "rate_limit", "internal_error", "network"
    ] = "none"
    summary: str = ""
    recommendations: list[str] = Field(default_factory=list)
