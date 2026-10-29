"""Tests for chunker, retriever hybrid merge, and vectorstore delete/upsert (mocked)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.ats_constants import ContactInfo
from core.chunker import chunk_profile
from core.profile_schema import ExperienceEntry, ProfileData
from core.retriever import EvidenceHit, RetrievalBundle, _merge_hits, format_evidence_for_prompt
from core.vectorstore import RetrievedChunk, ResumeChunk


def _profile() -> ProfileData:
    return ProfileData(
        contact=ContactInfo(name="Ada"),
        summary="Python backend engineer.",
        skills=["Python", "Kubernetes"],
        experience=[
            ExperienceEntry(
                id="exp-1",
                title="Engineer",
                company="Acme",
                start_date="January 2020",
                end_date="Present",
                bullets=["Built k8s platforms", "Shipped APIs"],
            )
        ],
    )


def test_chunk_profile_typed_chunks() -> None:
    chunks = chunk_profile(_profile(), user_id=7)
    types = {c.chunk_type for c in chunks}
    assert "summary" in types
    assert "skill_group" in types
    assert "experience" in types
    assert "bullet" in types
    assert all(c.id.startswith("u7-") for c in chunks)
    bullets = [c for c in chunks if c.chunk_type == "bullet"]
    assert all(b.parent_id == "exp-1" for b in bullets)


def test_merge_hits_prefers_both_source() -> None:
    vector = [
        RetrievedChunk(
            id="c1",
            text="Built k8s platforms",
            chunk_type="bullet",
            entry_id="exp-1-b0",
            parent_id="exp-1",
            distance=0.2,
            score=0.8,
        )
    ]
    alias = [
        EvidenceHit(
            chunk_id="c1",
            text="Built k8s platforms",
            chunk_type="bullet",
            entry_id="exp-1-b0",
            parent_id="exp-1",
            score=0.9,
            source="alias",
            query="Kubernetes",
        )
    ]
    merged = _merge_hits(vector, alias, "Kubernetes")
    assert len(merged) == 1
    assert merged[0].source == "both"
    assert merged[0].score >= 0.9


def test_format_evidence_for_prompt() -> None:
    bundle = RetrievalBundle(
        hits=[
            EvidenceHit("a", "Alpha", "bullet", "e1", "e1", 0.9, "vector"),
            EvidenceHit("b", "Beta", "bullet", "e2", "e2", 0.5, "alias"),
        ]
    )
    text = format_evidence_for_prompt(bundle, limit=5)
    assert "Alpha" in text
    assert "Beta" in text


@patch("core.vectorstore.get_collection")
@patch("core.vectorstore.embed_texts", return_value=[[0.1, 0.2], [0.3, 0.4]])
def test_reindex_deletes_stale_chunks(mock_embed, mock_get_collection) -> None:
    from core.vectorstore import upsert_chunks

    collection = MagicMock()
    collection.get.return_value = {"ids": ["old-1", "old-2"]}
    mock_get_collection.return_value = collection

    chunks = [
        ResumeChunk(id="new-1", text="hello", chunk_type="summary"),
        ResumeChunk(id="new-2", text="world", chunk_type="skill_group"),
    ]
    count = upsert_chunks(42, chunks)
    assert count == 2
    collection.delete.assert_called_once_with(ids=["old-1", "old-2"])
    collection.upsert.assert_called_once()
    args = collection.upsert.call_args.kwargs
    assert args["ids"] == ["new-1", "new-2"]
