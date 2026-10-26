"""Chunk ProfileData into typed ResumeChunk documents for Chroma."""

from __future__ import annotations

from core.profile_schema import ProfileData
from core.vectorstore import ResumeChunk


def chunk_profile(profile: ProfileData, *, user_id: int) -> list[ResumeChunk]:
    """Build typed evidence chunks from a structured master profile."""
    chunks: list[ResumeChunk] = []
    uid = int(user_id)

    if (profile.summary or "").strip():
        chunks.append(
            ResumeChunk(
                id=f"u{uid}-summary",
                text=profile.summary.strip(),
                chunk_type="summary",
                entry_id="summary",
            )
        )

    if profile.skills:
        text = "Skills: " + ", ".join(profile.skills)
        chunks.append(
            ResumeChunk(
                id=f"u{uid}-skills",
                text=text,
                chunk_type="skill_group",
                entry_id="skills",
            )
        )
    for idx, cat in enumerate(profile.skill_categories or []):
        items = cat.items or []
        if not items:
            continue
        chunks.append(
            ResumeChunk(
                id=f"u{uid}-skillcat-{idx}",
                text=f"{cat.category}: {', '.join(items)}",
                chunk_type="skill_group",
                entry_id=f"skillcat-{idx}",
            )
        )

    for entry in profile.experience:
        eid = entry.id or f"exp-{len(chunks)}"
        header = f"{entry.title} at {entry.company} ({entry.start_date} - {entry.end_date})"
        chunks.append(
            ResumeChunk(
                id=f"u{uid}-exp-{eid}",
                text=header,
                chunk_type="experience",
                entry_id=eid,
            )
        )
        for b_idx, bullet in enumerate(entry.bullets or []):
            if not (bullet or "").strip():
                continue
            chunks.append(
                ResumeChunk(
                    id=f"u{uid}-exp-{eid}-b{b_idx}",
                    text=bullet.strip(),
                    chunk_type="bullet",
                    entry_id=f"{eid}-b{b_idx}",
                    parent_id=eid,
                )
            )

    for entry in profile.projects:
        eid = entry.id or f"proj-{len(chunks)}"
        header = f"Project: {entry.title}" + (f" ({entry.company})" if entry.company else "")
        chunks.append(
            ResumeChunk(
                id=f"u{uid}-proj-{eid}",
                text=header,
                chunk_type="project",
                entry_id=eid,
            )
        )
        for b_idx, bullet in enumerate(entry.bullets or []):
            if not (bullet or "").strip():
                continue
            chunks.append(
                ResumeChunk(
                    id=f"u{uid}-proj-{eid}-b{b_idx}",
                    text=bullet.strip(),
                    chunk_type="bullet",
                    entry_id=f"{eid}-b{b_idx}",
                    parent_id=eid,
                )
            )

    for entry in profile.education:
        eid = entry.id or f"edu-{len(chunks)}"
        text = f"{entry.title} — {entry.company} ({entry.start_date} - {entry.end_date})"
        chunks.append(
            ResumeChunk(
                id=f"u{uid}-edu-{eid}",
                text=text,
                chunk_type="education",
                entry_id=eid,
            )
        )

    for idx, cert in enumerate(profile.certifications or []):
        if not (cert or "").strip():
            continue
        chunks.append(
            ResumeChunk(
                id=f"u{uid}-cert-{idx}",
                text=cert.strip(),
                chunk_type="certification",
                entry_id=f"cert-{idx}",
            )
        )

    return chunks


def reindex_profile(user_id: int, profile: ProfileData) -> int:
    """Chunk and upsert profile into Chroma. Returns number of chunks indexed."""
    from core.vectorstore import upsert_chunks

    chunks = chunk_profile(profile, user_id=user_id)
    return upsert_chunks(user_id, chunks)
