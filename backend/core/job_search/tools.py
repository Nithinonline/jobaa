from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.orm import Session, sessionmaker

from core.job_search import sources
from core.matcher import compute_match_result
from core.ats_scorer import score_resume
from core.profile_schema import ProfileData
from db.models import JobListing

MAX_SEARCH_ROUNDS = 3
MAX_TOOL_CALLS = 12
logger = logging.getLogger(__name__)


def normalize_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    port = parsed.port
    netloc = host if port in (None, 443) else f"{host}:{port}"
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in {"gh_src", "source", "ref"}]
    query.sort()
    return urlunsplit(("https", netloc, path, urlencode(query), ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()


@dataclass
class DiscoveryRunContext:
    user_id: int
    profile: ProfileData
    session_factory: sessionmaker
    max_age_days: int
    remote_only: bool = False
    progress_callback: Callable[[str], None] | None = None
    pool: dict[int, dict[str, Any]] = field(default_factory=dict)
    score_results: dict[int, dict[str, Any]] = field(default_factory=dict)
    details_read: set[int] = field(default_factory=set)
    source_errors: list[str] = field(default_factory=list)
    tool_calls: int = 0
    scout_tool_calls: int = 0
    source_calls: int = 0
    source_calls_by_tool: dict[str, int] = field(default_factory=dict)

    def start_call(self, *, search: bool = False, source_tool: str = "", scout_tool: bool = False) -> str | None:
        self.tool_calls += 1
        if scout_tool:
            self.scout_tool_calls += 1
            if self.scout_tool_calls > MAX_TOOL_CALLS:
                return f"Job Scout tool-call limit reached ({MAX_TOOL_CALLS})."
        if search:
            self.source_calls += 1
            if self.source_calls > MAX_TOOL_CALLS:
                return f"Search tool-call limit reached ({MAX_TOOL_CALLS})."
            count = self.source_calls_by_tool.get(source_tool, 0) + 1
            self.source_calls_by_tool[source_tool] = count
            if self.source_calls > MAX_SEARCH_ROUNDS * 3 or count > MAX_SEARCH_ROUNDS:
                return f"Search limit reached (maximum {MAX_SEARCH_ROUNDS} search calls per search tool)."
        return None

    def emit(self, detail: str) -> None:
        if self.progress_callback:
            self.progress_callback(detail)


def _already_seen(context: DiscoveryRunContext, hashes: list[str]) -> set[str]:
    if not hashes:
        return set()
    with context.session_factory() as session:
        rows = session.query(JobListing.url_hash).filter(
            JobListing.user_id == context.user_id,
            JobListing.url_hash.in_(hashes),
        ).all()
    return {row[0] for row in rows}


def _summary(job_id: int, job: dict[str, Any]) -> dict[str, Any]:
    posted = job["posted_at"]
    return {
        "job_id": job_id,
        "title": job["title"],
        "company": job["company"],
        "location": job["location"],
        "posted_at": posted.isoformat() if isinstance(posted, datetime) else str(posted),
        "snippet": job["jd_text"][:240],
    }


def _collect(context: DiscoveryRunContext, jobs: list[dict[str, Any]], *, label: str) -> list[dict[str, Any]]:
    fresh = sources.filter_by_age(jobs, context.max_age_days)
    candidates: list[tuple[str, dict[str, Any]]] = []
    for job in fresh:
        if context.remote_only and not job.get("remote"):
            continue
        source = str(job.get("source", ""))
        if not sources.validate_job_url(str(job.get("url", "")), source):
            continue
        normalized = dict(job)
        normalized["url"] = normalize_url(str(job["url"]))
        candidates.append((url_hash(normalized["url"]), normalized))
    hashes = [hash_value for hash_value, _ in candidates]
    seen = _already_seen(context, hashes)
    run_seen = {url_hash(record["url"]) for record in context.pool.values()}
    summaries = []
    for hash_value, job in candidates:
        if hash_value in seen or hash_value in run_seen:
            continue
        job_id = len(context.pool) + 1
        context.pool[job_id] = job
        run_seen.add(hash_value)
        summaries.append(_summary(job_id, job))
        if len(summaries) >= 25:
            break
    context.emit(f"{label}: {len(summaries)} new validated posting(s); pool has {len(context.pool)}.")
    return summaries


def search_adzuna_impl(context: DiscoveryRunContext, keywords: str, location: str, remote_only: bool, max_age_days: int) -> str:
    limit_error = context.start_call(search=True, source_tool="adzuna", scout_tool=True)
    if limit_error:
        return json.dumps({"jobs": [], "error": limit_error})
    if not keywords.strip():
        return json.dumps({"jobs": [], "error": "Search keywords cannot be empty."})
    if not 1 <= max_age_days <= 365:
        return json.dumps({"jobs": [], "error": "max_age_days must be between 1 and 365."})
    try:
        jobs, error = sources.search_adzuna(keywords, location, remote_only)
        if error:
            context.source_errors.append(error)
        return json.dumps({"jobs": _collect(context, jobs, label="Adzuna"), "error": error})
    except Exception as exc:
        logger.exception("Unexpected Adzuna search failure")
        context.source_errors.append(f"Adzuna search failed: {exc}")
        return json.dumps({"jobs": [], "error": str(exc)})


def search_remote_boards_impl(context: DiscoveryRunContext, keywords: str, max_age_days: int) -> str:
    limit_error = context.start_call(search=True, source_tool="remote_boards", scout_tool=True)
    if limit_error:
        return json.dumps({"jobs": [], "error": limit_error})
    if not keywords.strip():
        return json.dumps({"jobs": [], "error": "Search keywords cannot be empty."})
    errors, jobs = [], []
    for source_name, search in (("Remotive", sources.search_remotive), ("RemoteOK", sources.search_remoteok)):
        try:
            records, error = search(keywords)
        except Exception as exc:
            logger.exception("Unexpected %s search failure", source_name)
            records, error = [], f"{source_name} search failed: {exc}"
        jobs.extend(records)
        if error:
            errors.append(error)
            context.source_errors.append(error)
    return json.dumps({"jobs": _collect(context, jobs, label="Remote boards"), "error": "; ".join(errors) or None})


def search_company_boards_impl(context: DiscoveryRunContext, keywords: str) -> str:
    limit_error = context.start_call(search=True, source_tool="company_boards", scout_tool=True)
    if limit_error:
        return json.dumps({"jobs": [], "error": limit_error})
    if not keywords.strip():
        return json.dumps({"jobs": [], "error": "Search keywords cannot be empty."})
    jobs, error = sources.search_company_boards(keywords)
    if error:
        context.source_errors.append(error)
    return json.dumps({"jobs": _collect(context, jobs, label="Company boards"), "error": error})


def check_seen_jobs_impl(context: DiscoveryRunContext, urls: str) -> str:
    limit_error = context.start_call(scout_tool=True)
    if limit_error:
        return json.dumps({"error": limit_error})
    try:
        parsed = json.loads(urls) if urls.lstrip().startswith("[") else [part.strip() for part in urls.splitlines() if part.strip()]
        if not isinstance(parsed, list):
            raise ValueError("urls must be a JSON array or newline-delimited URLs")
        hashes = {url_hash(url) for url in parsed if isinstance(url, str) and sources._is_https_url(url)}
        seen = _already_seen(context, list(hashes))
        return json.dumps({"seen_url_hashes": sorted(seen), "checked": len(hashes)})
    except (ValueError, TypeError) as exc:
        return json.dumps({"error": str(exc)})


def get_job_details_impl(context: DiscoveryRunContext, job_id: int) -> str:
    limit_error = context.start_call()
    if limit_error:
        return json.dumps({"error": limit_error})
    job = context.pool.get(job_id)
    if job is None:
        return json.dumps({"error": "Unknown job_id for this search run."})
    context.emit(f"Fit Analyst: reading job {job_id} ({job['title']}).")
    context.details_read.add(job_id)
    return json.dumps({"job_id": job_id, "title": job["title"], "company": job["company"], "jd_text": job["jd_text"][:30000]})


def score_job_impl(context: DiscoveryRunContext, job_id: int) -> str:
    limit_error = context.start_call()
    if limit_error:
        return json.dumps({"error": limit_error})
    job = context.pool.get(job_id)
    if job is None:
        return json.dumps({"error": "Unknown job_id for this search run."})
    context.emit(f"Fit Analyst: scoring job {job_id} ({job['title']}).")
    result = compute_match_result(context.profile, job["jd_text"])
    score = min(100.0, max(0.0, float(result.score)))
    ats_score, _ats_summary, _ats_missing = score_resume(context.profile.to_prompt_text(), job["jd_text"])
    scored = {
        "job_id": job_id,
        "match_score": score,
        "ats_score": float(ats_score),
        "matched_keywords": result.matched,
        "missing_keywords": result.missing,
    }
    context.score_results[job_id] = scored
    return json.dumps(scored)


def create_crewai_tools(context: DiscoveryRunContext) -> list[Any]:
    try:
        from crewai.tools import tool
    except ImportError as exc:
        raise RuntimeError("CrewAI is required for agentic job discovery. Install project requirements.") from exc

    @tool("search_adzuna")
    def search_adzuna(keywords: str, location: str, remote_only: bool, max_age_days: int) -> str:
        """Search Adzuna for current listings matching keywords and location."""
        return search_adzuna_impl(context, keywords, location, remote_only, max_age_days)

    @tool("search_remote_boards")
    def search_remote_boards(keywords: str, max_age_days: int) -> str:
        """Search Remotive and RemoteOK public remote job boards."""
        if not 1 <= max_age_days <= 365:
            return json.dumps({"jobs": [], "error": "max_age_days must be between 1 and 365."})
        return search_remote_boards_impl(context, keywords, max_age_days)

    @tool("search_company_boards")
    def search_company_boards(keywords: str) -> str:
        """Search configured Greenhouse and Lever public job boards."""
        return search_company_boards_impl(context, keywords)

    @tool("check_seen_jobs")
    def check_seen_jobs(urls: str) -> str:
        """Check which newline-separated or JSON-array HTTPS listing URLs are already saved."""
        return check_seen_jobs_impl(context, urls)

    @tool("get_job_details")
    def get_job_details(job_id: int) -> str:
        """Read the full job description for a job returned by this run's search tools."""
        return get_job_details_impl(context, job_id)

    @tool("score_job")
    def score_job(job_id: int) -> str:
        """Calculate deterministic match score and matched/missing profile keywords."""
        return score_job_impl(context, job_id)

    return [search_adzuna, search_remote_boards, search_company_boards, check_seen_jobs, get_job_details, score_job]
