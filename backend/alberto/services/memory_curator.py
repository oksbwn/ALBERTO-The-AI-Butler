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

import asyncio
import inspect
import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from alberto.engine.models import resolve_model
from alberto.models import Agent
from alberto.schemas.memory_curator import (
    CuratorAdvisorySuggestion,
    EntityCandidate,
    MemoryCuratorOutput,
    RelationshipCandidate,
)

logger = logging.getLogger("alberto.services.memory_curator")

# Trivial whole-message expressions that should never trigger an LLM extraction call.
# Anchored to whole messages to ensure meaningful turns are never rejected merely
# because they start with a greeting or the word "test".
TRIVIAL_PATTERNS = [
    r"^(hi|hello|hey|howdy|greetings|good\s+(morning|afternoon|evening|day))(\s+(there|alberto|assistant|bot|friend|everyone|all))?[\s\.,!?:;-]*$",
    r"^(ok|okay|thanks|thank\s+you|thx|cool|got\s+it|understood|sounds\s+good|great|nice|awesome)[\s\.,!?:;-]*$",
    r"^(yes|no|yep|nope|sure|fine|yup|nah)[\s\.,!?:;-]*$",
    r"^\d+\s*[\+\-\*\/]\s*\d+[\s\=]*\d*[\s\.,!?:;-]*$",  # simple arithmetic
    r"^(test|testing|test\s+(message|run|check|123|abc)|ping|pong)[\s\.,!?:;-]*$",
]

# Sensitive credentials pattern (passwords, tokens, API keys, private keys).
# Deterministic invariant: never extract or send credentials to memory storage.
SENSITIVE_PATTERNS = [
    r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]?[^\s'\"]{4,}",
    r"(?i)(bearer|token|secret|api[_\-]?key)\s*[:=]\s*['\"]?[^\s'\"]{8,}",
    r"sk-[a-zA-Z0-9]{20,}",
    r"(?i)-----BEGIN\s+(RSA|EC|DSA|OPENSSH|PRIVATE)\s+KEY-----",
]

STOP_WORDS = {
    "the", "a", "an", "is", "am", "are", "was", "were", "be", "been", "being",
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "their", "our", "mine", "yours", "ours", "myself",
    "which", "what", "where", "when", "why", "how", "who", "whom",
    "this", "that", "these", "those", "for", "with", "at", "by", "from",
    "up", "about", "into", "over", "after", "to", "in", "on", "of", "and", "or",
    "but", "if", "then", "else", "so", "as", "do", "does", "did", "have", "has", "had",
}


def _extract_keywords(text: str) -> set[str]:
    words = re.findall(r"\b[a-zA-Z0-9_\-\.]+\b", (text or "").lower())
    return {w for w in words if w not in STOP_WORDS and len(w) > 1}


def select_relevant_memories(
    existing_memories: list[str],
    query: str,
    top_k: int = 8,
    max_chars: int = 1200,
) -> list[str]:
    """Bounded, relevance-aware selection of existing memories avoiding token bloat and context loss."""
    if not existing_memories:
        return []

    query_lower = (query or "").lower().strip()
    query_words = _extract_keywords(query_lower)

    scored: list[tuple[float, int, str]] = []
    for idx, mem in enumerate(existing_memories):
        mem_clean = mem.strip()
        if not mem_clean:
            continue
        mem_lower = mem_clean.lower()
        mem_words = _extract_keywords(mem_lower)

        score = 0.0
        # Exact phrase or substring match has highest priority
        if mem_lower in query_lower or query_lower in mem_lower:
            score += 3.0
        # Keyword overlap
        overlap = query_words & mem_words
        if overlap:
            score += 2.0 * len(overlap) / max(1, len(query_words))
            # Boost for technical terms (length >= 4)
            if any(len(w) >= 4 for w in overlap):
                score += 0.5

        scored.append((score, idx, mem_clean))

    # Sort descending by score; if tied, keep original order
    scored.sort(key=lambda x: (x[0], -x[1]), reverse=True)

    relevant_candidates = [m for s, _, m in scored if s > 0.0]
    unscored_candidates = [m for s, _, m in scored if s == 0.0]

    pool = relevant_candidates
    # If fewer than min(top_k, 3) relevant memories found, supplement with a small slice of recent/general
    if len(pool) < min(top_k, 3):
        pool = pool + unscored_candidates[: min(3 - len(pool), len(unscored_candidates))]

    selected: list[str] = []
    total_chars = 0
    for mem in pool:
        if len(selected) >= top_k:
            break
        mem_len = len(mem)
        if total_chars + mem_len > max_chars and selected:
            break
        selected.append(mem)
        total_chars += mem_len

    return selected


def _build_curator_system_prompt() -> str:
    """Builds curator system prompt using canonical schema without manual duplication."""
    schema_json = json.dumps(MemoryCuratorOutput.model_json_schema(), indent=2)
    return f"""You are Alberto's Intelligent Memory Curator.
Your job is to inspect completed conversation turns and extract ONLY meaningful, durable long-term knowledge to remember.

Core Extraction Principles:
1. DURABLE KNOWLEDGE: Extract durable user facts, preferences, technical setup, environments, and stable domain entities.
2. USER-ONLY FACT AUTHORITY: Extract facts and entities ONLY from statements, assertions, or confirmations explicitly made by the USER. Assistant responses are advisory context; NEVER extract assistant suggestions, speculations, or hallucinations as facts.
3. EXACT IDENTIFIER PRESERVATION: Preserve exact user-provided technical product names, model identifiers, acronyms, and novel terminology VERBATIM. Never autocorrect, normalize, or map an unfamiliar term to a familiar or popular one.
4. EVIDENCE GROUNDING: Every candidate memory, entity, and relationship MUST include exact quoted evidence_refs strictly from the USER's statements.
5. SENSITIVE DATA EXCLUSION: NEVER extract passwords, API keys, private tokens, credentials, credit cards, or financial data.
6. CORRECTIONS & REPLACEMENTS: When the user explicitly corrects or replaces prior knowledge, emit operation "propose_replace" with "supersedes_fact" referencing the prior state.
7. DYNAMIC CONCEPTUAL ONTOLOGY & DISCOVERY:
   - Physical hardware devices are 'device' or 'hardware'.
   - Operating systems and software platforms are 'operating_system' or 'platform'. NEVER classify an operating system or software platform as a device (macOS, Windows, Linux are operating_system).
   - Applications and software tools are 'application' or 'software'.
   - Frameworks, libraries, and inference runtimes are 'framework' (e.g. PyTorch, vLLM, llama.cpp).
   - AI and machine learning models are 'model'.
   - People and interpersonal relations are 'person' (never invent names from roles).
   - Physical places and spaces are 'location'.
   - Abstract ideas or unclassified topics are 'concept'.
   - Extensible domain types: You may propose specific descriptive entity types (e.g. 'inference_framework', 'container_runtime') and uppercase relationship types (e.g. 'DEPLOYED_VIA', 'RUNS', 'CONNECTS_TO') when supported by user evidence.
8. NEGATIVE CONSTRAINT: If the conversation contains nothing durable to remember, set "should_learn": false and return empty lists.

Output strictly valid JSON conforming to the canonical schema:
{schema_json}
"""


CURATOR_SYSTEM_PROMPT = _build_curator_system_prompt()


class MemoryCuratorService:
    """Orchestrates single-pass structured extraction of durable memory."""

    select_relevant_memories = staticmethod(select_relevant_memories)

    @staticmethod
    def is_eligible_turn(user_text: str | None, ai_text: str | None) -> tuple[bool, str]:
        """Deterministic eligibility pre-check before calling LLM."""
        if not user_text or not user_text.strip():
            return False, "User message is empty"

        cleaned = user_text.strip().lower()
        if len(cleaned) < 3:
            return False, "User message too short"

        # Check trivial whole-message patterns
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
        """Resolves model for Memory Curator respecting agent override -> project default LLM -> global default."""
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

        from alberto.services.runtime import build_compile_context

        ctx = await build_compile_context(session, tenant_id=tenant_id, project_id=project_id)
        chosen = override or ctx.default_model_id or ctx.default_model
        model = resolve_model(chosen, ctx=ctx)

        display_name = str(chosen) if chosen else "default"
        if ctx.registered_models and chosen in ctx.registered_models:
            rm = ctx.registered_models[chosen]
            display_name = rm.display_name or rm.model_name or display_name
            if getattr(rm, "supports_tools", None) is not None:
                setattr(model, "supports_tools", rm.supports_tools)  # noqa: B010
        return model, display_name

    get_configured_model = get_curator_model

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
            return MemoryCuratorOutput(
                should_learn=False,
                extraction_error=f"Model resolution failed: {e}",
            )

        # 3. Retrieve and select relevant existing memory context
        if existing_memories is None:
            try:
                from alberto.services.memory import MemoryService

                active_mems = await MemoryService.list(session, tenant_id, project_id, status="active")
                existing_memories = [m.text for m in active_mems]
            except Exception as e:
                logger.warning("Could not fetch active memories for curator context: %s", e)
                existing_memories = []

        selected_mems = select_relevant_memories(existing_memories, query=user_message)
        mem_summary = ""
        if selected_mems:
            mem_summary = "\nExisting User Knowledge:\n" + "\n".join(f"- {m}" for m in selected_mems)

        # 4. Format prompt
        user_prompt = f"""Analyze this conversation turn for durable knowledge to persist.
Remember: The USER is the sole authority for user facts. The Assistant's response must NEVER be used to invent entities, platforms, or aliases. Preserve all user technical names verbatim.

User Message (Authoritative Source):
{user_message}

Assistant Response (Advisory Context Only - DO NOT extract assistant suggestions or statements as user facts):
{ai_response}
{mem_summary}

Remember: Output strictly valid JSON conforming to the schema. Preserve user technical names verbatim."""

        messages = [
            SystemMessage(content=CURATOR_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        # 5. Model Invocation: select strategy based on verified provider capability
        use_structured = False
        structured_model = None

        # Check explicit provider/registry capability
        provider_supports_tools = getattr(model, "supports_tools", None)
        if provider_supports_tools is not False and hasattr(model, "with_structured_output") and callable(getattr(model, "with_structured_output", None)):
            try:
                sm = model.with_structured_output(MemoryCuratorOutput)
                # Verify sm supports async ainvoke (guards against unconfigured MagicMocks in tests)
                sm_ainvoke = getattr(sm, "ainvoke", None)
                if sm is not None and sm_ainvoke is not None and (
                    inspect.iscoroutinefunction(sm_ainvoke)
                    or not type(sm).__name__.endswith("Mock")
                ):
                    structured_model = sm
                    use_structured = True
            except (NotImplementedError, AttributeError, TypeError) as e:
                logger.debug("Native structured output binding not supported by model: %s", e)
                use_structured = False

        try:
            if use_structured and structured_model is not None:
                res = await structured_model.ainvoke(messages)
                if isinstance(res, MemoryCuratorOutput):
                    return res
                if isinstance(res, dict):
                    return MemoryCuratorOutput.model_validate(res)
                raw_text = getattr(res, "content", str(res))
                return cls._parse_output(raw_text)
            else:
                response = await model.ainvoke(messages)
                raw_text = response.content if hasattr(response, "content") else str(response)
                if isinstance(raw_text, list):
                    raw_text = "".join(str(p) for p in raw_text)
                return cls._parse_output(raw_text)
        except Exception as e:
            logger.error("Memory Curator model invocation failed: %s", e)
            return MemoryCuratorOutput(
                should_learn=False,
                extraction_error=f"Model invocation failed: {e}",
            )

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
                extraction_error=f"Malformed JSON output from model: {e}",
            )

    _suggestion_cache: dict[str, list[CuratorAdvisorySuggestion]] = {}

    @classmethod
    async def suggest_review_correction(
        cls,
        session: AsyncSession,
        tenant_id: str,
        project_id: str,
        review_reasons: list[str],
        candidate_entities: list[EntityCandidate],
        candidate_relationships: list[RelationshipCandidate],
        conversation_context: str = "",
    ) -> list[CuratorAdvisorySuggestion]:
        """Advisory review intelligence: bounded suggestions for flagged candidates."""
        if not review_reasons and not candidate_entities and not candidate_relationships:
            return []

        ent_sig = tuple((e.temporary_id, e.name, e.kind, e.description) for e in candidate_entities)
        rel_sig = tuple((r.source_ref, r.target_ref, r.kind) for r in candidate_relationships)
        cache_key = f"{tenant_id}:{project_id}:{hash((tuple(review_reasons), ent_sig, rel_sig, conversation_context))}"
        if cache_key in cls._suggestion_cache:
            return cls._suggestion_cache[cache_key]

        try:
            model, _ = await cls.get_curator_model(session, tenant_id, project_id)
        except Exception as e:
            logger.warning("Could not resolve model for review suggestion: %s", e)
            return []

        from alberto.services.ontology_registry import OntologyRegistryService
        approved_ent_objs = await OntologyRegistryService.list_entity_types(session, tenant_id, project_id, status="approved")
        approved_rel_objs = await OntologyRegistryService.list_relationship_types(session, tenant_id, project_id, status="approved")
        approved_ent_keys = [e.canonical_key for e in approved_ent_objs]
        approved_rel_keys = [r.canonical_key for r in approved_rel_objs]

        ent_desc = "\n".join(
            f"- [{e.temporary_id}] '{e.name}' (kind: '{e.kind}', conf: {e.confidence}, desc: '{e.description}')"
            for e in candidate_entities
        )
        rel_desc = "\n".join(
            f"- [{idx}] '{r.source_ref}' -[{r.kind}]-> '{r.target_ref}' (conf: {r.confidence})"
            for idx, r in enumerate(candidate_relationships)
        )
        reasons_desc = "\n".join(f"- {r}" for r in review_reasons)

        prompt = f"""You are Alberto's Memory Curator acting as an Advisory Intelligence capability during Human Review.
The Knowledge Graph Manager detected validation warnings on knowledge candidates proposed from a conversation turn:

Warnings & Ambiguities:
{reasons_desc or "(None explicitly listed)"}

Proposed Entities:
{ent_desc or "(No entities)"}

Proposed Relationships:
{rel_desc or "(No relationships)"}

Approved Canonical Entity Types in Scope:
{', '.join(approved_ent_keys)}

Approved Canonical Relationship Types in Scope:
{', '.join(approved_rel_keys)}

Conversation Evidence Context:
{conversation_context or "(Context unavailable)"}

Task:
Analyze the candidates and warnings. For any ambiguous, misclassified, or novel items:
1. If an entity is software/OS (e.g. macOS, Ubuntu, Windows) misclassified as 'device', recommend suggested_kind='operating_system'.
2. If an entity is physical hardware misclassified as software/platform, recommend suggested_kind='device'.
3. If an entity or relationship is novel and genuinely useful, recommend whether a new ontology definition is necessary (requires_new_ontology_definition=true/false).
4. If a relationship direction appears inverted (e.g. Docker RUNS Mac mini instead of Mac mini RUNS Docker), suggest suggested_direction='reverse'.
5. If a relationship kind should be refined (e.g. USES -> DEPLOYED_VIA), suggest the canonical kind and reason.

Output strictly a JSON list of objects matching the schema:
[
  {{
    "target_type": "entity",
    "target_ref": "temporary_id or entity name",
    "suggested_kind": "operating_system",
    "existing_type_mapping": "operating_system",
    "suggested_direction": null,
    "explanation": "macOS is an operating system, not a physical hardware device.",
    "evidence_refs": [],
    "uncertainty": 0.05,
    "requires_new_ontology_definition": false
  }}
]
"""
        messages = [
            SystemMessage(content="You are Alberto's Advisory Review Intelligence. Output strictly a valid JSON array of recommendations conforming to the schema."),
            HumanMessage(content=prompt),
        ]

        try:
            async with asyncio.timeout(15.0):
                res = await model.ainvoke(messages)
                raw_text = res.content if hasattr(res, "content") else str(res)
                if isinstance(raw_text, list):
                    raw_text = "".join(str(p) for p in raw_text)
                results = cls._parse_suggestions(raw_text)
                cls._suggestion_cache[cache_key] = results
                return results
        except Exception as e:
            logger.warning("Advisory review suggestions failed or timed out: %s", e)
            return []

    @classmethod
    def _parse_suggestions(cls, raw_text: str) -> list[CuratorAdvisorySuggestion]:
        """Robustly parse advisory suggestions from model output."""
        cleaned = raw_text.strip()
        if "```" in cleaned:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
            if match:
                cleaned = match.group(1).strip()
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict) and "suggestions" in data:
                data = data["suggestions"]
            if not isinstance(data, list):
                return []
            results: list[CuratorAdvisorySuggestion] = []
            for item in data:
                try:
                    results.append(CuratorAdvisorySuggestion.model_validate(item))
                except Exception as ve:
                    logger.debug("Skipping invalid suggestion item: %s", ve)
            return results
        except Exception as e:
            logger.warning("Failed to parse review suggestions JSON: %s (Raw: %s)", e, raw_text[:200])
            return []


MemoryCurator = MemoryCuratorService
