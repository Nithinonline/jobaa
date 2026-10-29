from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.job_search import sources
from core.job_search.tools import (
    DiscoveryRunContext,
    _collect,
    check_seen_jobs_impl,
    search_adzuna_impl,
    get_job_details_impl,
    normalize_url,
    score_job_impl,
    url_hash,
)
from core.profile_schema import ProfileData
from db.models import Base, JobListing, Profile, User


def _job(**overrides):
    value = {
        "title": "Python Engineer",
        "company": "Example",
        "location": "Remote",
        "remote": True,
        "url": "https://boards.greenhouse.io/example/jobs/123?utm_source=email",
        "posted_at": datetime.utcnow() - timedelta(days=1),
        "source": "greenhouse",
        "jd_text": "Build Python services and APIs.",
    }
    value.update(overrides)
    return value


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine), engine


def _context(factory, user_id=1):
    return DiscoveryRunContext(
        user_id=user_id,
        profile=ProfileData(skills=["Python"], summary="Python backend engineer"),
        session_factory=factory,
        max_age_days=14,
    )


def test_source_normalizes_adzuna_payload(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    response = MagicMock()
    response.json.return_value = {"results": [{
        "title": "Engineer", "company": {"display_name": "Acme"},
        "location": {"display_name": "London"},
        "redirect_url": "https://jobs.example.org/123", "created": "2026-10-25T10:00:00Z",
        "description": "Python systems role",
    }]}
    response.raise_for_status.return_value = None
    monkeypatch.setattr(sources.requests, "get", lambda *args, **kwargs: response)

    jobs, error = sources.search_adzuna("python", "London")

    assert error is None
    assert jobs[0]["title"] == "Engineer"
    assert jobs[0]["company"] == "Acme"
    assert jobs[0]["posted_at"] == datetime(2026, 10, 25, 10)
    assert jobs[0]["source"] == "adzuna"


def test_source_error_is_returned_without_raising(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    def fail(*args, **kwargs):
        raise sources.requests.Timeout("offline")
    monkeypatch.setattr(sources.requests, "get", fail)

    jobs, error = sources.search_adzuna("python")

    assert jobs == []
    assert error and "offline" in error.lower()


def test_url_validation_and_normalization():
    assert sources.validate_job_url("https://boards.greenhouse.io/acme/jobs/123", "greenhouse")
    assert not sources.validate_job_url("http://boards.greenhouse.io/acme/jobs/123", "greenhouse")
    assert not sources.validate_job_url("https://evil.example/123", "greenhouse")
    assert normalize_url("https://www.example.com/jobs/123/?utm_source=x#apply") == "https://example.com/jobs/123"


def test_age_filter_rejects_undated_old_and_future_jobs():
    now = datetime(2026, 10, 26)
    values = [
        _job(posted_at=now - timedelta(days=2)),
        _job(url="https://boards.greenhouse.io/example/jobs/old", posted_at=now - timedelta(days=30)),
        _job(url="https://boards.greenhouse.io/example/jobs/future", posted_at=now + timedelta(days=1)),
        _job(url="https://boards.greenhouse.io/example/jobs/unknown", posted_at=None),
    ]
    kept = sources.filter_by_age(values, 14, now=now)
    assert len(kept) == 1
    assert kept[0]["title"] == "Python Engineer"


def test_collection_deduplicates_and_skips_seen_for_same_user():
    factory, _engine = _db()
    with factory() as session:
        user = User(username="ada", email="ada@example.com", password_hash="hash")
        session.add(user)
        session.flush()
        listing = JobListing(
            user_id=user.id, url_hash=url_hash(_job()["url"]), url=_job()["url"],
            title="Old listing", company="Example", location="Remote", remote=True,
            posted_at=datetime.utcnow(), source="greenhouse", jd_text="Python", status="new",
        )
        session.add(listing)
        session.commit()
        context = _context(factory, user.id)

    fresh = _job(url="https://boards.greenhouse.io/example/jobs/456")
    summaries = _collect(context, [fresh, fresh], label="test")
    assert len(summaries) == 1
    assert summaries[0]["job_id"] == 1
    assert len(context.pool) == 1
    assert check_seen_jobs_impl(context, f"[\"{_job()['url']}\"]").find(url_hash(_job()["url"])) >= 0


def test_collect_skips_existing_listing_for_same_user():
    factory, _engine = _db()
    with factory() as session:
        user = User(username="ada", email="ada@example.com", password_hash="hash")
        session.add(user)
        session.flush()
        job = _job()
        session.add(JobListing(
            user_id=user.id, url_hash=url_hash(job["url"]), url=job["url"], title=job["title"],
            company=job["company"], location=job["location"], remote=True,
            posted_at=job["posted_at"], source="greenhouse", jd_text=job["jd_text"], status="new",
        ))
        session.commit()
        context = _context(factory, user.id)
    assert _collect(context, [_job()], label="test") == []


def test_score_job_uses_matcher_and_returns_numeric_result():
    factory, _engine = _db()
    context = _context(factory)
    context.pool[7] = _job()

    result = __import__("json").loads(score_job_impl(context, 7))

    assert 0 <= result["match_score"] <= 100
    assert isinstance(result["match_score"], (int, float))
    assert "python" in [term.lower() for term in result["matched_keywords"]]
    assert "ats_score" in result


def test_details_tool_only_reads_jobs_in_run_pool():
    factory, _engine = _db()
    context = _context(factory)
    assert "Unknown job_id" in get_job_details_impl(context, 1)
    context.pool[1] = _job()
    assert "Python services" in get_job_details_impl(context, 1)


def test_service_drops_agent_job_id_not_in_pool(monkeypatch):
    from core.job_discovery_crew import DiscoveryCrewResult
    from core.services.job_discovery_service import run_job_search

    factory, _engine = _db()
    with factory() as session:
        user = User(username="ada", email="ada@example.com", password_hash="hash")
        session.add(user)
        session.flush()
        profile = Profile(user_id=user.id, structured_profile_json=ProfileData(skills=["Python"]).model_dump_json())
        session.add(profile)
        session.commit()
        user_id = user.id

    def fake_crew(context, **kwargs):
        context.pool[1] = _job()
        context.score_results[1] = {"match_score": 75.5, "matched_keywords": ["Python"], "missing_keywords": []}
        return DiscoveryCrewResult(
            results=[{"job_id": 1, "match_score": 75.5, "fit_note": "Match", "gaps": [], "job": context.pool[1]},
                     {"job_id": 777, "match_score": 100, "fit_note": "Invented", "gaps": [], "job": {}}],
            fallback_note=None, source_errors=[], tool_calls=2, search_calls=1,
        )
    monkeypatch.setattr("core.services.job_discovery_service.run_job_discovery_crew", fake_crew)

    result = run_job_search(user_id, "", False, 14, 5, session_factory=factory)

    assert len(result["results"]) == 1
    assert result["results"][0]["title"] == "Python Engineer"
    with factory() as session:
        assert session.query(JobListing).filter_by(user_id=user_id).count() == 1


def test_scout_tool_calls_are_hard_limited():
    factory, _engine = _db()
    context = _context(factory)
    for _ in range(12):
        check_seen_jobs_impl(context, "[]")
    result = check_seen_jobs_impl(context, "[]")
    assert "limit reached" in result


def test_greenhouse_source_normalizes_public_board_response(monkeypatch):
    monkeypatch.setenv("GREENHOUSE_BOARDS", "example")
    sources._cache.clear()
    response = MagicMock()
    response.json.return_value = {"jobs": [{
        "title": "Python Engineer", "updated_at": "2026-10-25T12:00:00Z",
        "absolute_url": "https://boards.greenhouse.io/example/jobs/99",
        "location": {"name": "Remote - US"}, "content": "Build Python APIs",
    }]}
    response.raise_for_status.return_value = None
    monkeypatch.setattr(sources.requests, "get", lambda *args, **kwargs: response)

    jobs, error = sources.search_greenhouse("Python")

    assert error is None
    assert jobs[0]["source"] == "greenhouse"
    assert jobs[0]["company"] == "example"
    assert jobs[0]["remote"] is True
    assert jobs[0]["jd_text"] == "Build Python APIs"
