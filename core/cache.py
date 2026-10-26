from __future__ import annotations

import hashlib
from typing import Optional

from sqlalchemy.orm import Session

from core.jd_parser import ParsedJobDescription, parsed_to_db_fields
from db.models import JobDescription


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def find_cached_job_description(session: Session, user_id: int, raw_text: str) -> Optional[JobDescription]:
    if not raw_text.strip():
        return None
    content_hash = hash_text(raw_text)
    return (
        session.query(JobDescription)
        .filter(JobDescription.user_id == user_id, JobDescription.content_hash == content_hash)
        .first()
    )


def get_or_create_job_description(
    session: Session,
    user_id: int,
    raw_text: str,
    title: str,
    *,
    source_url: str | None = None,
    parsed: ParsedJobDescription | None = None,
) -> JobDescription:
    cached = find_cached_job_description(session, user_id, raw_text)
    if cached is not None:
        if title and title != "Untitled role":
            cached.title = title
        if source_url:
            cached.source_url = source_url
        if parsed:
            _apply_parsed_job_description(cached, parsed)
        session.commit()
        session.refresh(cached)
        return cached

    parsed = parsed or ParsedJobDescription(title=title or "Untitled role")
    content_hash = hash_text(raw_text)
    jd = JobDescription(
        user_id=user_id,
        title=title or parsed.title or "Untitled role",
        raw_text=raw_text,
        content_hash=content_hash,
        source_url=source_url,
    )
    _apply_parsed_job_description(jd, parsed)
    session.add(jd)
    session.commit()
    session.refresh(jd)
    return jd


def _apply_parsed_job_description(
    jd: JobDescription,
    parsed: ParsedJobDescription,
) -> None:
    for field, value in parsed_to_db_fields(parsed).items():
        setattr(jd, field, value)
    jd.title = parsed.title or jd.title
