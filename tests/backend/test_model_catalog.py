"""Model-catalog integrity.

CHAT_MODELS is the single source of truth for default model fallbacks, and the
model a blank ("Project default") node actually runs must be selectable in the UI.
"""

from __future__ import annotations

from alberto.engine.models import _PROVIDER_CHEAP_MODEL
from alberto.model_catalog import CHAT_MODELS, EMBEDDING_MODELS, RERANKER_MODELS


def test_cheap_defaults_are_selectable():
    # cheap_model_for_credentials picks these when a node leaves the model blank (e.g. the
    # classifier's "Project default"); each must be in the catalog so the UI can show what runs.
    ids = {m.id for m in CHAT_MODELS}
    for default in _PROVIDER_CHEAP_MODEL.values():
        assert default in ids, f"cheap default {default} is not in the model catalog"


def test_no_duplicate_model_ids():
    ids = [m.id for m in CHAT_MODELS]
    assert len(ids) == len(set(ids)), "duplicate model id in CHAT_MODELS"


def test_embedding_default_matches_backend():
    # The picker's default embedder must be the one the backend actually falls back to.
    from alberto.knowledge.embeddings import _DEFAULT_FASTEMBED

    defaults = [m for m in EMBEDDING_MODELS if m.default]
    assert len(defaults) == 1, "exactly one default embedding model"
    assert defaults[0].id.split(":", 1)[1] == _DEFAULT_FASTEMBED


def test_reranker_default_matches_backend():
    from alberto.knowledge.rerank import DEFAULT_RERANKER

    defaults = [m for m in RERANKER_MODELS if m.default]
    assert len(defaults) == 1, "exactly one default reranker"
    assert defaults[0].id == DEFAULT_RERANKER


def test_no_duplicate_ids_across_catalogs():
    all_ids = [m.id for m in CHAT_MODELS] + [m.id for m in EMBEDDING_MODELS] + [m.id for m in RERANKER_MODELS]
    assert len(all_ids) == len(set(all_ids)), "duplicate id across model catalogs"
