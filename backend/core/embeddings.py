"""SentenceTransformer embedding wrapper (lazy-loaded)."""

from __future__ import annotations

import sys
from typing import Sequence

from core.config_loader import get_embeddings_config

# Survives Streamlit evicting core.* from sys.modules on each script rerun.
_MODEL_ATTR = "_jobaa_embedding_model"


def _load_model():
    cached = getattr(sys, _MODEL_ATTR, None)
    if cached is not None:
        return cached
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(get_embeddings_config()["model"])
    setattr(sys, _MODEL_ATTR, model)
    return model


def get_embedding_model():
    """Return the cached SentenceTransformer model."""
    return _load_model()


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """Embed a list of strings; empty strings become zero-length skip with empty vector."""
    cleaned = [t if (t or "").strip() else " " for t in texts]
    if not cleaned:
        return []
    model = get_embedding_model()
    vectors = model.encode(list(cleaned), normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vectors]


def embed_query(text: str) -> list[float]:
    """Embed a single query string."""
    return embed_texts([text or " "])[0]
