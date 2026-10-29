"""Local Chroma persistent vector store for master-resume evidence chunks."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from core.config_loader import get_embeddings_config
from core.embeddings import embed_query, embed_texts


@dataclass
class ResumeChunk:
    """A typed chunk of the master resume for retrieval."""

    id: str
    text: str
    chunk_type: str  # summary | skill_group | experience | bullet | project | education | certification
    entry_id: str = ""
    parent_id: str = ""
    source: str = "master"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievedChunk:
    id: str
    text: str
    chunk_type: str
    entry_id: str
    parent_id: str
    distance: float
    score: float  # higher is better (1 - distance for cosine)


_client = None
_collection = None


def _chroma_path() -> Path:
    path = Path(get_embeddings_config()["chroma_path"])
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_chroma_client():
    global _client
    if _client is None:
        import chromadb

        _client = chromadb.PersistentClient(path=str(_chroma_path()))
    return _client


def get_collection(name: str | None = None):
    global _collection
    collection_name = name or get_embeddings_config()["collection"]
    if _collection is None or getattr(_collection, "name", None) != collection_name:
        client = get_chroma_client()
        _collection = client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def reset_vectorstore_cache() -> None:
    """Clear module-level client/collection (for tests)."""
    global _client, _collection
    _client = None
    _collection = None


def delete_user_chunks(user_id: int) -> None:
    """Remove all chunks for a user so reindex does not leave stale bullets."""
    collection = get_collection()
    try:
        existing = collection.get(where={"user_id": int(user_id)})
        ids = existing.get("ids") or []
        if ids:
            collection.delete(ids=ids)
    except Exception:
        # Empty collection or filter unsupported — try delete with empty result ignore
        pass


def upsert_chunks(user_id: int, chunks: list[ResumeChunk]) -> int:
    """Delete existing user chunks then upsert the provided set. Returns count upserted."""
    delete_user_chunks(user_id)
    if not chunks:
        return 0

    collection = get_collection()
    ids = [c.id for c in chunks]
    documents = [c.text for c in chunks]
    metadatas = [
        {
            "user_id": int(user_id),
            "chunk_type": c.chunk_type,
            "entry_id": c.entry_id or "",
            "parent_id": c.parent_id or "",
            "source": c.source or "master",
        }
        for c in chunks
    ]
    embeddings = embed_texts(documents)
    collection.upsert(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings,
    )
    return len(chunks)


def query_chunks(
    user_id: int,
    query_text: str,
    *,
    n_results: int | None = None,
    chunk_types: Optional[list[str]] = None,
) -> list[RetrievedChunk]:
    """Vector search filtered by user_id (and optional chunk_type)."""
    if not (query_text or "").strip():
        return []
    n = n_results if n_results is not None else int(get_embeddings_config()["n_results"])
    collection = get_collection()
    where: dict[str, Any] = {"user_id": int(user_id)}
    if chunk_types:
        if len(chunk_types) == 1:
            where = {"$and": [{"user_id": int(user_id)}, {"chunk_type": chunk_types[0]}]}
        else:
            where = {
                "$and": [
                    {"user_id": int(user_id)},
                    {"chunk_type": {"$in": chunk_types}},
                ]
            }

    try:
        result = collection.query(
            query_embeddings=[embed_query(query_text)],
            n_results=max(1, n),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        return []

    ids = (result.get("ids") or [[]])[0]
    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    dists = (result.get("distances") or [[]])[0]

    out: list[RetrievedChunk] = []
    for i, chunk_id in enumerate(ids):
        dist = float(dists[i]) if i < len(dists) else 1.0
        meta = metas[i] if i < len(metas) else {}
        out.append(
            RetrievedChunk(
                id=chunk_id,
                text=docs[i] if i < len(docs) else "",
                chunk_type=str(meta.get("chunk_type") or ""),
                entry_id=str(meta.get("entry_id") or ""),
                parent_id=str(meta.get("parent_id") or ""),
                distance=dist,
                score=max(0.0, 1.0 - dist),
            )
        )
    return out
