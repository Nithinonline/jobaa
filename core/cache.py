from __future__ import annotations

import hashlib
from typing import Optional

from sqlalchemy.orm import Session

from core.jd_parser import parse_job_description, parsed_to_db_fields
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
) -> JobDescription:
    cached = find_cached_job_description(session, user_id, raw_text)
    if cached is not None:
        return cached

    parsed = parse_job_description(raw_text)
    db_fields = parsed_to_db_fields(parsed)
    content_hash = hash_text(raw_text)
    jd = JobDescription(
        user_id=user_id,
        title=title or parsed.title or "Untitled role",
        raw_text=raw_text,
        content_hash=content_hash,
        skills=db_fields["skills"],
        preferred_skills=db_fields["preferred_skills"],
        experience=db_fields["experience"],
        technologies=db_fields["technologies"],
        responsibilities=db_fields["responsibilities"],
        keywords=db_fields["keywords"],
    )
    session.add(jd)
    session.commit()
    session.refresh(jd)
    return jd
