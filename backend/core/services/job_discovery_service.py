from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from core.job_search.tools import DiscoveryRunContext, normalize_url, url_hash
from core.profile_schema import ProfileData
from core.services.profile_service import load_profile_data
from db.models import JobListing, Profile
from db.session import SessionLocal

logger = logging.getLogger(__name__)
Progress = dict[str, dict[str, str]]
ProgressCallback = Callable[[Progress], None]
VALID_STATUSES = {"new", "saved", "applied", "ignored"}


def run_job_discovery_crew(*args: Any, **kwargs: Any) -> Any:
    from core.job_discovery_crew import run_job_discovery_crew as run_crew

    return run_crew(*args, **kwargs)


def _profile_is_searchable(profile: ProfileData | None) -> bool:
    if profile is None:
        return False
    return bool(
        profile.summary.strip()
        or profile.skills
        or profile.skill_categories
        or profile.experience
        or profile.projects
        or profile.education
        or profile.certifications
    )


def run_job_search(
    user_id: int,
    location: str,
    remote_only: bool,
    max_age_days: int,
    top_n: int,
    *,
    progress_callback: ProgressCallback | None = None,
    session_factory: sessionmaker = SessionLocal,
) -> dict[str, Any]:
    if not 1 <= max_age_days <= 365:
        raise ValueError("Maximum posting age must be between 1 and 365 days.")
    if not 1 <= top_n <= 20:
        raise ValueError("Number of results must be between 1 and 20.")
    with session_factory() as session:
        profile_row = session.query(Profile).filter(Profile.user_id == user_id).first()
        profile_data = load_profile_data(profile_row) if profile_row else None
        if not _profile_is_searchable(profile_data):
            raise ValueError("Save a master resume with skills, experience, or a summary before finding jobs.")
        context = DiscoveryRunContext(
            user_id=user_id,
            profile=profile_data,
            session_factory=session_factory,
            max_age_days=max_age_days,
            remote_only=remote_only,
            progress_callback=lambda detail: _update_scout_detail(progress_callback, detail),
        )

    try:
        crew_result = run_job_discovery_crew(
            context,
            location=location.strip(),
            top_n=top_n,
            progress_callback=progress_callback or (lambda _progress: None),
        )
        saved: list[dict[str, Any]] = []
        with session_factory() as session:
            for result in crew_result.results:
                job_id = result.get("job_id")
                if not isinstance(job_id, int) or job_id not in context.pool:
                    logger.warning("Dropping discovery result with unknown pool id %r", job_id)
                    continue
                record = context.pool[job_id]
                score = result.get("match_score")
                score_record = context.score_results.get(job_id)
                if score_record is None:
                    from core.matcher import compute_match_result
                    score_record_obj = compute_match_result(profile_data, record["jd_text"])
                    score_record = {
                        "match_score": float(score_record_obj.score),
                        "matched_keywords": score_record_obj.matched,
                        "missing_keywords": score_record_obj.missing,
                    }
                score = max(0.0, min(100.0, float(score_record["match_score"])))
                hash_value = url_hash(record["url"])
                existing = session.query(JobListing).filter(
                    JobListing.user_id == user_id,
                    JobListing.url_hash == hash_value,
                ).first()
                if existing:
                    continue
                listing = JobListing(
                    user_id=user_id,
                    url_hash=hash_value,
                    url=normalize_url(record["url"]),
                    title=record["title"],
                    company=record["company"],
                    location=record["location"],
                    remote=bool(record["remote"]),
                    posted_at=record["posted_at"],
                    source=record["source"],
                    jd_text=record["jd_text"],
                    match_score=score,
                    fit_note=str(result.get("fit_note", ""))[:1000],
                    status="new",
                )
                try:
                    with session.begin_nested():
                        session.add(listing)
                        session.flush()
                except IntegrityError:
                    logger.info("Concurrent search already persisted listing hash %s", hash_value)
                    continue
                saved.append(_listing_dict(listing, result))
            session.commit()
        estimated_tokens = sum(len(job.get("jd_text", "")) for job in context.pool.values()) // 4
        estimated_tokens += len(profile_data.to_prompt_text()) // 4
        logger.info(
            "Job search user_id=%s pool=%d returned=%d tool_calls=%d search_calls=%d "
            "estimated_text_tokens=%d source_errors=%d",
            user_id, len(context.pool), len(saved), crew_result.tool_calls,
            crew_result.search_calls, estimated_tokens, len(crew_result.source_errors),
        )
        return {
            "results": saved,
            "fallback_note": crew_result.fallback_note,
            "source_errors": crew_result.source_errors,
            "candidate_count": len(context.pool),
            "tool_calls": crew_result.tool_calls,
            "search_calls": crew_result.search_calls,
            "estimated_text_tokens": estimated_tokens,
        }
    except Exception:
        logger.exception("Job discovery failed for user_id=%s", user_id)
        raise


def _update_scout_detail(callback: ProgressCallback | None, detail: str) -> None:
    if callback is None:
        return
    # Copying is handled by the caller's progress renderer; service emits a consistent stage map.
    is_analyst = detail.startswith("Fit Analyst:")
    callback({
        "query_planner": {"status": "completed", "detail": "Search plan prepared"},
        "job_scout": {"status": "completed" if is_analyst else "running", "detail": "Candidate collection complete" if is_analyst else detail},
        "fit_analyst": {"status": "running" if is_analyst else "queued", "detail": detail if is_analyst else ""},
    })


def _listing_dict(listing: JobListing, result: dict[str, Any]) -> dict[str, Any]:
    job = result["job"]
    return {
        "id": listing.id,
        "job_id": result["job_id"],
        "url": listing.url,
        "title": listing.title,
        "company": listing.company,
        "location": listing.location,
        "remote": listing.remote,
        "posted_at": listing.posted_at.isoformat(),
        "source": listing.source,
        "jd_text": listing.jd_text,
        "match_score": listing.match_score,
        "fit_note": listing.fit_note,
        "gaps": result.get("gaps", []),
        "matched_keywords": result.get("matched_keywords", []),
        "status": listing.status,
        "created_at": listing.created_at.isoformat() if listing.created_at else None,
    }


def update_job_status(session: Session, user_id: int, listing_id: int, status: str) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid job status: {status}")
    listing = session.query(JobListing).filter(
        JobListing.id == listing_id,
        JobListing.user_id == user_id,
    ).first()
    if listing is None:
        raise ValueError("Job listing not found for this user.")
    listing.status = status
    session.commit()


def list_job_listings(session: Session, user_id: int, status: str | None = None) -> list[JobListing]:
    query = session.query(JobListing).filter(JobListing.user_id == user_id)
    if status is not None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid job status: {status}")
        query = query.filter(JobListing.status == status)
    else:
        query = query.filter(JobListing.status != "ignored")
    return query.order_by(JobListing.match_score.desc(), JobListing.posted_at.desc()).all()
