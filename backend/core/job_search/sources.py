from __future__ import annotations

import copy
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlparse

import requests

TIMEOUT_SECONDS = 8
SOURCE_CAP = 25
CACHE_TTL_SECONDS = 6 * 60 * 60
_USER_AGENT = "Joba job discovery (public API client)"
_cache: dict[tuple[Any, ...], tuple[float, list[dict[str, Any]]]] = {}
_cache_lock = threading.Lock()
logger = logging.getLogger(__name__)


def _cached(key: tuple[Any, ...], loader: Callable[[], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(key)
        if entry and now - entry[0] < CACHE_TTL_SECONDS:
            return copy.deepcopy(entry[1])
    results = loader()
    with _cache_lock:
        _cache[key] = (now, copy.deepcopy(results))
    return results


def _request_json(url: str, *, params: dict[str, Any] | None = None) -> Any:
    response = requests.get(
        url,
        params=params,
        timeout=TIMEOUT_SECONDS,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
    )
    response.raise_for_status()
    return response.json()


def _date(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000 if value > 10_000_000_000 else value, tz=timezone.utc).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _is_https_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value.strip())
        port = parsed.port
    except ValueError:
        return False
    return parsed.scheme.lower() == "https" and bool(parsed.hostname) and parsed.username is None and parsed.password is None and port in (None, 443)


def _normalize(
    *, title: Any, company: Any, location: Any, remote: Any, url: Any,
    posted_at: Any, jd_text: Any, source: str,
) -> dict[str, Any] | None:
    title_text = str(title or "").strip()
    company_text = str(company or "").strip()
    url_text = str(url or "").strip()
    date_value = _date(posted_at)
    if not title_text or not company_text or not _is_https_url(url_text) or date_value is None:
        return None
    jd_value = " ".join(str(jd_text or "").split())
    return {
        "title": title_text[:300],
        "company": company_text[:300],
        "location": str(location or "Not specified").strip()[:300],
        "remote": bool(remote),
        "url": url_text,
        "posted_at": date_value,
        "source": source,
        "jd_text": jd_value[:30000],
    }


def _safe_source_call(source: str, cache_key: tuple[Any, ...], loader: Callable[[], list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], str | None]:
    try:
        return _cached((source, *cache_key), loader)[:SOURCE_CAP], None
    except Exception as exc:
        logger.warning("Job source %s failed: %s", source, exc, exc_info=True)
        return [], f"{source} search failed: {exc}"


def search_adzuna(keywords: str, location: str = "", remote_only: bool = False) -> tuple[list[dict[str, Any]], str | None]:
    terms = " ".join(keywords.split())[:200]
    where = " ".join(location.split())[:120]
    def load() -> list[dict[str, Any]]:
        app_id, app_key = os.getenv("ADZUNA_APP_ID", "").strip(), os.getenv("ADZUNA_APP_KEY", "").strip()
        if not app_id or not app_key:
            raise ValueError("ADZUNA_APP_ID and ADZUNA_APP_KEY are required")
        country = os.getenv("ADZUNA_COUNTRY", "gb").strip().lower()
        if not country.isalpha() or len(country) != 2:
            raise ValueError("ADZUNA_COUNTRY must be a two-letter country code")
        data = _request_json(f"https://api.adzuna.com/v1/api/jobs/{country}/search/1", params={
            "app_id": app_id, "app_key": app_key, "results_per_page": SOURCE_CAP,
            "what": terms, "where": where, "content-type": "application/json",
        })
        records = []
        for item in data.get("results", []):
            loc = item.get("location") or {}
            remote_hint = " ".join((str(loc.get("display_name", "")), str(item.get("title", "")), str(item.get("description", "")))).lower()
            remote = "remote" in remote_hint or "work from home" in remote_hint
            if remote_only and not remote:
                continue
            result = _normalize(
                title=item.get("title"), company=(item.get("company") or {}).get("display_name"),
                location=loc.get("display_name"), remote=remote, url=item.get("redirect_url"),
                posted_at=item.get("created"), jd_text=item.get("description"), source="adzuna",
            )
            if result:
                records.append(result)
        return records
    return _safe_source_call("adzuna", (terms.casefold(), where.casefold(), remote_only), load)


def search_remotive(keywords: str) -> tuple[list[dict[str, Any]], str | None]:
    terms = " ".join(keywords.split())[:200]
    def load() -> list[dict[str, Any]]:
        data = _request_json("https://remotive.com/api/remote-jobs", params={"search": terms, "limit": SOURCE_CAP})
        records = []
        for item in data.get("jobs", []):
            result = _normalize(
                title=item.get("title"), company=item.get("company_name"), location=item.get("candidate_required_location"),
                remote=True, url=item.get("url"), posted_at=item.get("publication_date"),
                jd_text=item.get("description"), source="remotive",
            )
            if result:
                records.append(result)
        return records
    return _safe_source_call("remotive", (terms.casefold(),), load)


def search_remoteok(keywords: str) -> tuple[list[dict[str, Any]], str | None]:
    terms = " ".join(keywords.split())[:200]
    def load() -> list[dict[str, Any]]:
        data = _request_json("https://remoteok.com/api", params={"tag": terms})
        records = []
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict) or not item.get("position"):
                continue
            slug = item.get("slug")
            link = item.get("url") or (f"https://remoteok.com/remote-jobs/{slug}" if slug else "")
            result = _normalize(
                title=item.get("position"), company=item.get("company"), location=item.get("location") or "Remote",
                remote=True, url=link, posted_at=item.get("date"), jd_text=item.get("description"), source="remoteok",
            )
            if result:
                records.append(result)
        return records
    return _safe_source_call("remoteok", (terms.casefold(),), load)


def _configured_boards(env_name: str) -> list[str]:
    return sorted({slug.strip() for slug in os.getenv(env_name, "").replace(";", ",").split(",") if slug.strip()})


def _greenhouse_board(slug: str, terms: set[str]) -> tuple[list[dict[str, Any]], str | None]:
    if not slug.replace("-", "").isalnum():
        return [], f"Invalid Greenhouse board slug: {slug}"
    try:
        data = _request_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", params={"content": "true"})
        records = []
        for item in data.get("jobs", []):
            desc = item.get("content", "")
            haystack = f"{item.get('title', '')} {desc}".casefold()
            if terms and not any(term in haystack for term in terms):
                continue
            loc = (item.get("location") or {}).get("name")
            record = _normalize(
                title=item.get("title"), company=slug, location=loc, remote="remote" in str(loc).lower(),
                url=item.get("absolute_url"), posted_at=item.get("updated_at"), jd_text=desc, source="greenhouse",
            )
            if record:
                records.append(record)
        return records, None
    except Exception as exc:
        logger.warning("Greenhouse board %s failed: %s", slug, exc, exc_info=True)
        return [], f"Greenhouse/{slug}: {exc}"


def search_greenhouse(keywords: str) -> tuple[list[dict[str, Any]], str | None]:
    terms = {term.casefold() for term in keywords.split() if len(term) > 2}
    boards = _configured_boards("GREENHOUSE_BOARDS")
    if not boards:
        return [], "GREENHOUSE_BOARDS is not configured"
    def load() -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=min(5, len(boards)), thread_name_prefix="greenhouse-board") as executor:
            futures = [executor.submit(_greenhouse_board, slug, terms) for slug in boards[:10]]
            for future in as_completed(futures):
                board_records, error = future.result()
                records.extend(board_records)
                if error:
                    errors.append(error)
        if errors and not records:
            raise ValueError("; ".join(errors))
        return records
    return _safe_source_call("greenhouse", (keywords.casefold(), tuple(boards)), load)

def _lever_board(slug: str, terms: set[str]) -> tuple[list[dict[str, Any]], str | None]:
    if not slug.replace("-", "").isalnum():
        return [], f"Invalid Lever board slug: {slug}"
    try:
        data = _request_json(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"})
        records = []
        for item in data if isinstance(data, list) else []:
            desc = item.get("descriptionPlain") or item.get("description") or ""
            haystack = f"{item.get('text', '')} {desc}".casefold()
            if terms and not any(term in haystack for term in terms):
                continue
            categories = item.get("categories") or {}
            loc = categories.get("location") or "Not specified"
            record = _normalize(
                title=item.get("text"), company=slug, location=loc, remote="remote" in str(loc).lower(),
                url=item.get("hostedUrl") or item.get("applyUrl"), posted_at=item.get("createdAt"),
                jd_text=desc, source="lever",
            )
            if record:
                records.append(record)
        return records, None
    except Exception as exc:
        logger.warning("Lever board %s failed: %s", slug, exc, exc_info=True)
        return [], f"Lever/{slug}: {exc}"


def search_lever(keywords: str) -> tuple[list[dict[str, Any]], str | None]:
    terms = {term.casefold() for term in keywords.split() if len(term) > 2}
    boards = _configured_boards("LEVER_BOARDS")
    if not boards:
        return [], "LEVER_BOARDS is not configured"
    def load() -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=min(5, len(boards)), thread_name_prefix="lever-board") as executor:
            futures = [executor.submit(_lever_board, slug, terms) for slug in boards[:10]]
            for future in as_completed(futures):
                board_records, error = future.result()
                records.extend(board_records)
                if error:
                    errors.append(error)
        if errors and not records:
            raise ValueError("; ".join(errors))
        return records
    return _safe_source_call("lever", (keywords.casefold(), tuple(boards)), load)

def search_company_boards(keywords: str) -> tuple[list[dict[str, Any]], str | None]:
    greenhouse, greenhouse_error = search_greenhouse(keywords)
    lever, lever_error = search_lever(keywords)
    errors = "; ".join(error for error in (greenhouse_error, lever_error) if error)
    return (greenhouse + lever)[:SOURCE_CAP], errors or None


def filter_by_age(jobs: list[dict[str, Any]], max_age_days: int, *, now: datetime | None = None) -> list[dict[str, Any]]:
    if max_age_days < 1:
        raise ValueError("max_age_days must be at least 1")
    current = now or datetime.now(timezone.utc).replace(tzinfo=None)
    if current.tzinfo:
        current = current.astimezone(timezone.utc).replace(tzinfo=None)
    cutoff = current - timedelta(days=max_age_days)
    kept = []
    for job in jobs:
        posted = _date(job.get("posted_at"))
        if posted is not None and posted <= current and posted >= cutoff:
            normalized = dict(job)
            normalized["posted_at"] = posted
            kept.append(normalized)
    return kept


def validate_job_url(url: str, source: str) -> bool:
    if not _is_https_url(url):
        return False
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    allowed = {
        "remotive": ("remotive.com",),
        "remoteok": ("remoteok.com",),
        "greenhouse": ("greenhouse.io",),
        "lever": ("lever.co",),
        "adzuna": (),
    }.get(source)
    if allowed is None:
        return False
    if source == "adzuna":
        return True
    return any(host == domain or host.endswith("." + domain) for domain in allowed)
