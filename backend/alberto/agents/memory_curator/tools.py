"""Memory Curator & Knowledge StructuredTools."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool

from alberto.db.base import SessionLocal
from alberto.services.knowledge import KnowledgeService


def build_memory_curator_tools(tenant_id: str, project_id: str, mutated: list, current_user: Any = None) -> list:
    """Build Knowledge & Q&A StructuredTools for a project."""

    async def add_qa_pair(question: str, answer: str, kind: str = "faq") -> str:
        """Add a Q&A pair to the knowledge base so the workflow can answer this question with
        this exact answer. `kind` is a free-form category - 'faq', 'error_workaround', or any
        custom kind the user wants (retrieval nodes and agent Q&A can filter by it)."""
        async with SessionLocal() as s:
            qa = await KnowledgeService.create_qa(s, tenant_id, project_id, question=question, answer=answer, kind=kind or "faq")
        mutated.append({"kind": "qa", "name": question[:40]})
        return f"Added Q&A pair ({qa.kind}): '{question[:60]}' (id {qa.id})."

    async def add_knowledge_text(name: str, text: str, folder: str = "") -> str:
        """Add a document of text to the knowledge base (it is split, embedded, and made
        searchable for grounding). `folder` (optional, free-form) organizes sources -
        retrieval nodes and knowledge_search tools can filter by folder."""
        async with SessionLocal() as s:
            src = await KnowledgeService.create_source(s, tenant_id, project_id, kind="text", name=name, text=text, folder=folder)
            src = await KnowledgeService.ingest(s, src)
        mutated.append({"kind": "knowledge", "name": name})
        if src.status != "ready":
            return f"ERROR ingesting '{name}': {(src.meta or {}).get('error', 'unknown')}."
        where = f" in folder '{folder}'" if folder else ""
        return f"Added knowledge source '{name}'{where} ({src.chunks} chunk(s), embedded)."

    def mk(fn, name):
        return StructuredTool.from_function(coroutine=fn, name=name, parse_docstring=False)

    return [
        mk(add_qa_pair, "add_qa_pair"),
        mk(add_knowledge_text, "add_knowledge_text"),
    ]

