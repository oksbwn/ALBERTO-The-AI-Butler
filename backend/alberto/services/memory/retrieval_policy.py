"""Retrieval Routing Policy: Intelligent source selection and bounded fallback.

Determines the most appropriate knowledge sources (memory, graph, qa, knowledge, markdown)
for a given user message using deterministic heuristics and context signals,
avoiding unnecessary queries to every memory store on every chat turn.
"""

from __future__ import annotations

import re
from typing import Any

# Logical retrieval sources supported by UnifiedMemoryManager
SOURCE_MEMORY = "memory"
SOURCE_GRAPH = "graph"
SOURCE_QA = "qa"
SOURCE_KNOWLEDGE = "knowledge"
SOURCE_MARKDOWN = "markdown"

ALL_SOURCES = [SOURCE_MEMORY, SOURCE_GRAPH, SOURCE_QA, SOURCE_KNOWLEDGE]

# General knowledge and greeting patterns that require zero personal memory retrieval
GENERAL_QUERY_PATTERNS = [
    r"^(what|who|where|when|why|how)\s+(is|are|was|were|does|do)\s+[a-z0-9\s\-_+/*=]+(\?|$)",
    r"^(hi|hello|hey|good\s+morning|good\s+evening|greetings)[\s!.]*$",
    r"^(thank|thanks|ok|okay|got\s+it|understood|cool|sure)[\s!.]*$",
    r"^(write|code|create|implement|generate|explain|describe|define)\s+(a|an|the|me|some)?\s*",
    r"^(\d+\s*[\+\-\*\/]\s*\d+)",
]

# Words that indicate general programming or factual queries without personal context
GENERAL_TOPICS = {
    "python", "javascript", "typescript", "rust", "golang", "c++", "java", "html", "css",
    "docker", "kubernetes", "linux", "git", "bash", "sql", "postgres", "redis",
    "react", "nextjs", "vue", "angular", "fastapi", "django", "flask",
}


class RetrievalPolicy:
    """Lightweight deterministic retrieval routing policy."""

    @classmethod
    def select_sources(
        cls,
        query: str,
        context: dict[str, Any] | None = None,
    ) -> list[str]:
        """Select preferred retrieval sources for a user query.

        Priority order:
        1. Explicit user references (e.g. "search my documents", "in the graph", "saved q&a").
        2. Domain heuristics (devices/connections -> graph+memory; decisions/preferences -> memory; faqs -> qa; docs -> knowledge).
        3. General question detection (zero personal memory required).
        """
        q = (query or "").strip().lower()
        if not q or len(q) < 3:
            return []

        # Check explicit context overrides if provided
        if context and "preferred_sources" in context:
            pref = [s for s in context["preferred_sources"] if s in ALL_SOURCES]
            if pref:
                return pref

        selected: list[str] = []

        # 1. Explicit user keywords / references
        has_doc_hint = bool(re.search(r"\b(pdf|document|documents|docs|uploaded|file|files|manual|paper|article)\b", q))
        has_qa_hint = bool(re.search(r"\b(faq|faqs|q&a|q\s+and\s+a|saved\s+q&a|question\s+and\s+answer)\b", q))
        has_graph_hint = bool(re.search(r"\b(graph|connected|connection|topology|device|devices|network|runs|running\s+on|attached\s+to|server)\b", q))
        has_memory_hint = bool(re.search(r"\b(remember|memory|memories|prefer|preference|preferences|about\s+me|my\s+name|my\s+decision|earlier|yesterday|last\s+time|we\s+talked|told\s+you)\b", q))

        if has_doc_hint:
            selected.append(SOURCE_KNOWLEDGE)
        if has_qa_hint:
            selected.append(SOURCE_QA)
        if has_graph_hint:
            selected.append(SOURCE_GRAPH)
            if has_memory_hint or "server" in q or "device" in q:
                selected.append(SOURCE_MEMORY)
        if has_memory_hint and SOURCE_MEMORY not in selected:
            selected.append(SOURCE_MEMORY)

        if selected:
            # Deduplicate while preserving order
            return list(dict.fromkeys(selected))

        # 2. Specific intent-based heuristics
        # Decision / past history / notes -> memory + knowledge (if concept-related)
        if re.search(r"\b(decision|decided|agreed|discussed|plan|planned|choice)\b", q):
            return [SOURCE_MEMORY, SOURCE_KNOWLEDGE]

        # Personal profile or preferences
        if re.search(r"\b(i\s+like|i\s+prefer|my\s+favorite|my\s+home|my\s+setup|my\s+work)\b", q):
            return [SOURCE_MEMORY]

        # Entity relationships, tech stack, and device locations
        if re.search(r"\b(where\s+is|which\s+device|what\s+is\s+on|host|ip\s+address|port|framework|stack|inference)\b", q):
            return [SOURCE_MEMORY, SOURCE_GRAPH]

        # 3. Check for general coding / factual question with NO personal context
        is_general_pattern = any(re.search(pat, q) for pat in GENERAL_QUERY_PATTERNS)
        has_first_person = bool(re.search(r"\b(i|me|my|mine|we|our|us|myself)\b", q))

        if is_general_pattern and not has_first_person:
            return []

        # 4. Default conservative fallback: if query has first-person personal terms, query memory
        if has_first_person:
            return [SOURCE_MEMORY]

        # Default for ambiguous queries: start with memory
        return [SOURCE_MEMORY]

    @classmethod
    def get_fallback_sources(
        cls,
        initial_sources: list[str],
        result_count: int = 0,
    ) -> list[str]:
        """Compute bounded fallback sources when initial retrieval returns insufficient evidence.

        Ensures at most a single bounded broadening step and prevents cyclic or all-source loops.
        """
        if result_count > 0:
            return []

        initial_set = set(initial_sources)

        # If graph lookup returned empty, try semantic memory for entities
        if SOURCE_GRAPH in initial_set and SOURCE_MEMORY not in initial_set:
            return [SOURCE_MEMORY]

        # If document RAG returned empty, try curated Q&A or memory
        if SOURCE_KNOWLEDGE in initial_set and len(initial_set) == 1:
            return [SOURCE_QA]

        # If Q&A returned empty, try document knowledge
        if SOURCE_QA in initial_set and len(initial_set) == 1:
            return [SOURCE_KNOWLEDGE]

        return []


def select_sources(query: str, context: dict[str, Any] | None = None, requested_sources: list[str] | None = None) -> list[str]:
    """Module-level helper for selecting sources."""
    ctx = dict(context or {})
    if requested_sources:
        ctx["preferred_sources"] = requested_sources
    return RetrievalPolicy.select_sources(query, ctx)


def get_fallback_sources(initial_sources: list[str], result_count: int = 0) -> list[str]:
    """Module-level helper for fallback sources."""
    return RetrievalPolicy.get_fallback_sources(initial_sources, result_count)
