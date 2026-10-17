"""Memory Curator Service: Single-pass structured extraction of durable facts and entities.

Enforces:
- Single structured LLM invocation per eligible conversation turn.
- System-agent model inheritance: Agent config override -> Global default model.
- Strict negative constraints:
  * No entity invention.
  * No personal names invented from roles.
  * No persistence of passwords, tokens, API keys, or financial credentials.
  * No persistence of transient tool errors, debug logs, or intermediate reasoning.
  * Explicit user corrections detected as replacements.
- Deterministic eligibility and sensitive-information guards prior to LLM call.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.config import settings
from alberto.engine.models import resolve_model
from alberto.models import Agent
from alberto.schemas.memory_curator import MemoryCuratorOutput

logger = logging.getLogger("alberto.services.memory_curator")

# Trivial expressions that should never trigger an LLM extraction call
TRIVIAL_PATTERNS = [
    r"^(hi|hello|hey|howdy|good\s+(morning|afternoon|evening))\b",
    r"^(ok|okay|thanks|thank\s+you|thx|cool|got\s+it|understood|sounds\s+good)[\.\!\?]?$",
    r"^(yes|no|yep|nope|sure|fine)[\.\!\?]?$",
    r"^\d+\s*[\+\-\*\/]\s*\d+[\s\=]*\d*$",  # simple arithmetic
    r"^test\b",
]

# Sensitive credentials pattern
SENSITIVE_PATTERNS = [
    r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]?[^\s'\"]{4,}",
    r"(?i)(bearer|token|secret|api[_\-]?key)\s*[:=]\s*['\"]?[^\s'\"]{8,}",
    r"sk-[a-zA-Z0-9]{20,}",
    r"(?i)-----BEGIN\s+(RSA|EC|DSA|OPENSSH|PRIVATE)\s+KEY-----",
]

CURATOR_SYSTEM_PROMPT = """You are Alberto's Intelligent Memory Curator.
Your job is to inspect completed conversation turns and extract ONLY meaningful, durable long-term knowledge to remember.

Extraction Targets:
1. Durable user facts & preferences (e.g. favorite tools, technical setup, habits, routines).
2. Stable home & device descriptions (e.g. Mac mini, Linux server, smart lights).
3. Candidate entities and typed relationships (e.g. (Mac mini)-[RUNS]->(LM Studio)).
4. Corrections or replacements to prior facts (e.g. if the user replaced Qwen with Gemma).

Strict Negative Constraints (CRITICAL):
- DO NOT invent entities, names, dates, or values not explicitly stated in the conversation.
- DO NOT invent personal names from roles (e.g. if user says "My wife's birthday is June 4", role is "wife", DO NOT invent a first or last name).
- DO NOT treat speculative assistant suggestions or tool errors as confirmed facts.
- DO NOT extract passwords, API keys, private tokens, credit cards, or financial identifiers.
- DO NOT extract temporary conversation chatter ("ok", "thank you", intermediate math, weather queries).
- Every memory and entity MUST include evidence_refs (exact text quotes or message identifiers).
- If the conversation contains nothing durable to remember, set "should_learn": false and return empty lists.

Output strictly valid JSON matching this schema:
{
  "schema_version": 1,
  "should_learn": true | false,
  "memories": [
    {
      "kind": "preference" | "fact" | "technology" | "home" | "profile" | "project",
      "content": "Factual statement",
      "confidence": 0.0 - 1.0,
      "durability": "long_term" | "ephemeral",
      "evidence_refs": ["quoted user statement"],
      "operation": "propose_upsert" | "propose_replace" | "propose_delete",
      "supersedes_fact": "Description of older fact if replacing, else null"
    }
  ],
  "entities": [
    {
      "temporary_id": "e1",
      "name": "Entity Name",
      "kind": "device" | "application" | "person" | "location" | "service" | "concept",
      "confidence": 0.0 - 1.0,
      "description": "Short description",
      "aliases": [],
      "evidence_refs": ["quoted text"]
    }
  ],
  "relationships": [
    {
      "source_ref": "e1",
      "target_ref": "e2",
      "kind": "RUNS" | "PREFERS" | "USES" | "LOCATED_IN" | "OWNS" | "RELATES_TO",
      "confidence": 0.0 - 1.0,
      "evidence_refs": ["quoted text"]
    }
  ],
  "conflicts": [],
  "requires_review": false
}
"""


class MemoryCuratorService:
    """Orchestrates single-pass structured extraction of durable memory."""

    @staticmethod
    def is_eligible_turn(user_text: str | None, ai_text: str | None) -> tuple[bool, str]:
        """Deterministic eligibility pre-check before calling LLM."""
        if not user_text or not user_text.strip():
            return False, "User message is empty"

        cleaned = user_text.strip().lower()
        if len(cleaned) < 3:
            return False, "User message too short"

        # Check trivial patterns
        for pat in TRIVIAL_PATTERNS:
            if re.search(pat, cleaned, re.IGNORECASE):
                return False, f"Message matches trivial pattern: {pat}"

        # Sensitive information exclusion
        for pat in SENSITIVE_PATTERNS:
            if re.search(pat, user_text):
                return False, "Message contains sensitive credentials (passwords, tokens, or keys)"

        return True, "Eligible"

    @classmethod
    async def get_curator_model(
        cls, session: AsyncSession, tenant_id: str, project_id: str
    ) -> tuple[Any, str]:
        """Resolves model for Memory Curator respecting agent override -> global default."""
        agent = (
            await session.execute(
                select(Agent).where(
                    Agent.tenant_id == tenant_id,
                    Agent.project_id == project_id,
                    Agent.system_key == "memory_curator",
                )
            )
        ).scalar_one_or_none()

        override = (agent.config.get("model") if agent and agent.config else None) or None

        from alberto.engine.context import CompileContext

        ctx = CompileContext(
            tenant_id=tenant_id,
            project_id=project_id,
            default_model=settings.default_model,
        )
        model = resolve_model(override, ctx=ctx)
        effective_name = override or settings.default_model
        return model, effective_name

    @classmethod
    async def extract(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        user_message: str,
        ai_response: str,
        existing_memories: list[str] | None = None,
    ) -> MemoryCuratorOutput:
        """Execute single-pass structured extraction using the configured system agent model."""
        # 1. Eligibility pre-check
        eligible, reason = cls.is_eligible_turn(user_message, ai_response)
        if not eligible:
            logger.debug("Turn ineligible for memory extraction: %s", reason)
            return MemoryCuratorOutput(should_learn=False)

        # 2. Resolve model
        try:
            model, model_name = await cls.get_curator_model(session, tenant_id, project_id)
        except Exception as e:
            logger.warning("Could not resolve model for Memory Curator: %s", e)
            return MemoryCuratorOutput(should_learn=False)

        # 3. Format prompt
        mem_summary = ""
        if existing_memories:
            mem_summary = "\nExisting User Knowledge:\n" + "\n".join(f"- {m}" for m in existing_memories[:10])

        user_prompt = f"""Analyze this conversation turn for durable knowledge to persist.

User: {user_message}
Assistant: {ai_response}
{mem_summary}

Remember: Output strictly valid JSON conforming to the schema."""

        # 4. Invoke LLM
        messages = [
            SystemMessage(content=CURATOR_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        try:
            response = await model.ainvoke(messages)
            raw_text = response.content if hasattr(response, "content") else str(response)
            if isinstance(raw_text, list):
                # multi-part content
                raw_text = "".join(str(p) for p in raw_text)
        except Exception as e:
            logger.error("Memory Curator model invocation failed: %s", e)
            return MemoryCuratorOutput(
                should_learn=False,
                extraction_error="Model invocation failed",
            )

        # 5. Clean & Parse JSON
        return cls._parse_output(raw_text)

    @classmethod
    def _parse_output(cls, raw_text: str) -> MemoryCuratorOutput:
        """Robustly parse and validate JSON from model output."""
        cleaned = raw_text.strip()
        # Handle markdown ```json code blocks
        if "```" in cleaned:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
            if match:
                cleaned = match.group(1).strip()

        try:
            data = json.loads(cleaned)
            return MemoryCuratorOutput.model_validate(data)
        except Exception as e:
            logger.warning("Failed to parse Memory Curator JSON output: %s (Raw: %s)", e, raw_text[:200])
            return MemoryCuratorOutput(
                should_learn=False,
                requires_review=False,
                extraction_error="Malformed JSON output from model",
            )
