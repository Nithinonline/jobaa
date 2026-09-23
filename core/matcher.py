"""Deterministic, weighted profile-to-JD match scoring."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Optional

from core.jd_parser import job_description_to_parsed
from core.profile_schema import ProfileData
from core.skill_aliases import expand_aliases, normalize_skill_token, tokens_match

if TYPE_CHECKING:
    from db.models import JobDescription

# Lightweight stopword set for JD fallback tokenization (avoid importing ats_scorer → llm).
_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with",
    "by", "from", "as", "is", "was", "are", "were", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "must",
    "shall", "can", "need", "our", "your", "their", "this", "that", "these", "those", "we",
    "you", "they", "it", "its", "who", "which", "what", "when", "where", "why", "how", "all",
    "each", "every", "both", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "just", "also", "into", "over",
    "about", "above", "after", "before", "between", "during", "under", "again", "further",
    "then", "once", "here", "there", "any", "if", "while", "through", "work", "working",
    "role", "job", "position", "candidate", "team", "company", "experience", "years", "year",
    "ability", "able", "including", "etc", "using", "use", "used", "we", "need",
})

# Component weights (sum to 1.0). Years weight redistributes to skills when unparseable.
_W_REQUIRED = 0.50
_W_PREFERRED = 0.20
_W_TITLE = 0.15
_W_YEARS = 0.15

_MONTH_MAP = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_DATE_TOKEN = re.compile(
    r"(?P<month>january|february|march|april|may|june|july|august|september|"
    r"october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"\s+(?P<year>\d{4})"
    r"|(?P<year_only>\d{4})",
    re.IGNORECASE,
)

_YEARS_RANGE = re.compile(
    r"(?P<min>\d+)\s*[-–to]+\s*(?P<max>\d+)\s*(?:\+)?\s*(?:years?|yrs?)?",
    re.IGNORECASE,
)
_YEARS_PLUS = re.compile(
    r"(?P<min>\d+)\s*\+\s*(?:years?|yrs?)?",
    re.IGNORECASE,
)
_YEARS_MIN = re.compile(
    r"(?:at\s+least\s+|minimum\s+of\s+|min(?:imum)?\s+)?(?P<min>\d+)\s*(?:years?|yrs?)",
    re.IGNORECASE,
)

_TITLE_STOP = frozenset(
    {
        "senior",
        "junior",
        "staff",
        "lead",
        "principal",
        "associate",
        "i",
        "ii",
        "iii",
        "iv",
        "sr",
        "jr",
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "for",
        "to",
        "in",
        "at",
        "with",
    }
)


@dataclass
class MatchResult:
    score: float
    matched_required: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    matched_preferred: list[str] = field(default_factory=list)
    missing_preferred: list[str] = field(default_factory=list)
    components: dict[str, float | None] = field(default_factory=dict)

    @property
    def matched(self) -> list[str]:
        return list(dict.fromkeys(self.matched_required + self.matched_preferred))

    @property
    def missing(self) -> list[str]:
        return list(dict.fromkeys(self.missing_required + self.missing_preferred))


@dataclass
class _JDTermBuckets:
    required: list[str]
    preferred: list[str]
    title: str
    experience_years: str


def _tokenize_phrase(text: str) -> list[str]:
    parts = re.split(r"[\s,/|;]+", text or "")
    out: list[str] = []
    for part in parts:
        norm = normalize_skill_token(part)
        if norm and len(norm) > 1:
            out.append(norm)
    return out


def _fallback_jd_tokens(jd_text: str, limit: int = 40) -> list[str]:
    """Extract significant tech-like tokens from raw JD text (no isalpha filter)."""
    terms = re.findall(r"[a-zA-Z0-9+#.\-]+", (jd_text or "").lower())
    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        if len(term) <= 1 or term in _STOP_WORDS:
            continue
        if term in seen:
            continue
        seen.add(term)
        out.append(term)
        if len(out) >= limit:
            break
    return out


def extract_jd_terms(
    jd: Optional["JobDescription"],
    jd_text: str,
) -> _JDTermBuckets:
    """Full scoring keyword sets — not capped like get_priority_keywords."""
    if jd is not None:
        parsed = job_description_to_parsed(jd)
        required = list(
            dict.fromkeys(
                [t for t in (parsed.required_skills + parsed.technologies) if t.strip()]
            )
        )
        preferred_raw = list(
            dict.fromkeys(
                [t for t in (parsed.preferred_skills + parsed.keywords) if t.strip()]
            )
        )
        required_lower = {t.lower() for t in required}
        preferred = [t for t in preferred_raw if t.lower() not in required_lower]
        return _JDTermBuckets(
            required=required,
            preferred=preferred,
            title=parsed.title or (jd.title or ""),
            experience_years=parsed.experience_years or "",
        )

    tokens = _fallback_jd_tokens(jd_text)
    return _JDTermBuckets(
        required=tokens,
        preferred=[],
        title="",
        experience_years="",
    )


def profile_match_corpus(profile: ProfileData) -> set[str]:
    """Normalized tokens from skills/summary/experience/projects/certs — no contact."""
    tokens: set[str] = set()
    for skill in profile.all_skill_tokens():
        tokens |= expand_aliases(skill)
        tokens.update(_tokenize_phrase(skill))
    for text in [profile.summary, *profile.certifications, *profile.achievements]:
        for tok in _tokenize_phrase(text):
            tokens |= expand_aliases(tok)
    for entry in profile.experience + profile.projects + profile.education:
        for text in [entry.title, entry.company, *(entry.bullets or [])]:
            for tok in _tokenize_phrase(text):
                tokens |= expand_aliases(tok)
    return {t for t in tokens if t}


def term_in_corpus(term: str, corpus: set[str]) -> bool:
    """
    Match like skill_in_profile: equality, alias, or whole-token containment.
    Avoids substring false positives (java in javascript).
    """
    needle_forms = expand_aliases(term)
    if not needle_forms:
        return False

    # Direct equality / alias hit
    if needle_forms & corpus:
        return True

    for needle in needle_forms:
        for known in corpus:
            if tokens_match(needle, known):
                return True
            # Whole-token / phrase containment (not raw substring of unrelated words)
            if len(needle) >= 3 and (needle in known.split("-") or known in needle.split("-")):
                return True
            known_parts = set(_tokenize_phrase(known.replace("-", " ")))
            if needle in known_parts:
                return True
            # Multi-word needle: all tokens present
            needle_parts = _tokenize_phrase(needle.replace("-", " ").replace(".", " "))
            if len(needle_parts) > 1 and all(
                any(tokens_match(p, k) or p == k for k in corpus) for p in needle_parts
            ):
                return True
            # Containment only when needle is a full segment of known (hyphen/space bound)
            if len(needle) >= 3 and _whole_token_contained(needle, known):
                return True
    return False


def _whole_token_contained(needle: str, haystack: str) -> bool:
    """True if needle appears as a whole token inside haystack (not java⊂javascript)."""
    if needle == haystack:
        return True
    if len(needle) < 3:
        return False
    # Split haystack on non-alnum boundaries and compare
    parts = re.split(r"[^a-z0-9+#]+", haystack)
    if needle in parts:
        return True
    # Allow needle as prefix only when followed by a non-letter (e.g. node in node.js)
    if haystack.startswith(needle) and (
        len(haystack) == len(needle) or not haystack[len(needle)].isalpha()
    ):
        return True
    if haystack.endswith(needle) and (
        len(haystack) == len(needle) or not haystack[-len(needle) - 1].isalpha()
    ):
        return True
    return False


def _classify_terms(
    terms: list[str],
    corpus: set[str],
) -> tuple[list[str], list[str]]:
    matched: list[str] = []
    missing: list[str] = []
    for term in terms:
        if not term.strip():
            continue
        if term_in_corpus(term, corpus):
            matched.append(term)
        else:
            missing.append(term)
    return matched, missing


def _skill_ratio(matched: list[str], missing: list[str]) -> float:
    total = len(matched) + len(missing)
    if total == 0:
        return 100.0  # no requirements in this bucket → neutral full credit
    return 100.0 * len(matched) / total


def _title_tokens(title: str) -> set[str]:
    tokens = set()
    for tok in _tokenize_phrase(title):
        if tok not in _TITLE_STOP and len(tok) > 1:
            tokens.add(tok)
    return tokens


def _score_title(jd_title: str, profile: ProfileData) -> float:
    needed = _title_tokens(jd_title)
    if not needed:
        return 100.0
    profile_titles: set[str] = set()
    for entry in profile.experience + profile.projects:
        profile_titles |= _title_tokens(entry.title)
    if not profile_titles:
        return 0.0
    hits = 0
    for tok in needed:
        if any(tokens_match(tok, p) or tok in p or p in tok for p in profile_titles):
            hits += 1
    return 100.0 * hits / len(needed)


def _parse_date_token(text: str) -> date | None:
    text = (text or "").strip()
    if not text:
        return None
    if text.lower() in ("present", "current", "now"):
        return date.today()
    match = _DATE_TOKEN.search(text)
    if not match:
        return None
    if match.group("year_only"):
        return date(int(match.group("year_only")), 1, 1)
    month = _MONTH_MAP.get(match.group("month").lower())
    year = int(match.group("year"))
    if month is None:
        return None
    return date(year, month, 1)


def profile_years_experience(profile: ProfileData) -> float | None:
    """Sum non-overlapping tenure from experience entries; None if unparseable."""
    intervals: list[tuple[date, date]] = []
    for entry in profile.experience:
        start = _parse_date_token(entry.start_date)
        end = _parse_date_token(entry.end_date) or date.today()
        if start is None:
            continue
        if end < start:
            continue
        intervals.append((start, end))
    if not intervals:
        return None
    intervals.sort()
    # Merge overlapping intervals
    merged: list[tuple[date, date]] = [intervals[0]]
    for start, end in intervals[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    total_days = sum((end - start).days for start, end in merged)
    return round(total_days / 365.25, 2)


def parse_jd_years_required(experience_years: str) -> float | None:
    """Parse minimum years from JD strings like '3-5 years' or '5+'."""
    text = (experience_years or "").strip()
    if not text:
        return None
    m = _YEARS_RANGE.search(text)
    if m:
        return float(m.group("min"))
    m = _YEARS_PLUS.search(text)
    if m:
        return float(m.group("min"))
    m = _YEARS_MIN.search(text)
    if m:
        return float(m.group("min"))
    return None


def _score_years(jd_years_text: str, profile: ProfileData) -> float | None:
    """Return 0–100 years score, or None if JD years or profile tenure unparseable."""
    required = parse_jd_years_required(jd_years_text)
    if required is None:
        return None
    actual = profile_years_experience(profile)
    if actual is None:
        return None
    if required <= 0:
        return 100.0
    if actual >= required:
        return 100.0
    # Linear credit for partial years
    return round(100.0 * actual / required, 1)


def compute_match_result(
    profile: ProfileData,
    jd_text: str,
    jd: Optional["JobDescription"] = None,
) -> MatchResult:
    """
    Weighted deterministic match score (0–100).

    Components: required skills (0.50), preferred (0.20), title (0.15), years (0.15).
    Empty JD with no extractable terms → 0.0.
    """
    buckets = extract_jd_terms(jd, jd_text)
    has_any_signal = bool(
        buckets.required
        or buckets.preferred
        or buckets.title.strip()
        or buckets.experience_years.strip()
    )
    if not has_any_signal and not (jd_text or "").strip():
        return MatchResult(score=0.0, components={"required": 0.0, "preferred": 0.0, "title": 0.0, "years": 0.0})

    if not has_any_signal:
        # Raw text present but no tokens after filtering
        return MatchResult(score=0.0, components={"required": 0.0, "preferred": 0.0, "title": 0.0, "years": 0.0})

    corpus = profile_match_corpus(profile)
    matched_req, missing_req = _classify_terms(buckets.required, corpus)
    matched_pref, missing_pref = _classify_terms(buckets.preferred, corpus)

    required_score = _skill_ratio(matched_req, missing_req)
    preferred_score = _skill_ratio(matched_pref, missing_pref)
    title_score = _score_title(buckets.title, profile)
    years_score = _score_years(buckets.experience_years, profile)

    w_req = _W_REQUIRED
    w_pref = _W_PREFERRED
    w_title = _W_TITLE
    w_years = _W_YEARS

    if years_score is None:
        # Redistribute years weight into skills (required + preferred proportionally)
        skill_w = w_req + w_pref
        if skill_w > 0:
            w_req = w_req + w_years * (w_req / skill_w)
            w_pref = w_pref + w_years * (w_pref / skill_w)
        else:
            w_req = w_req + w_years
        w_years = 0.0
        years_component = 0.0
    else:
        years_component = years_score

    # If no required terms, give full credit for that bucket (already in _skill_ratio)
    # If no title, full credit — already handled in _score_title

    score = (
        required_score * w_req
        + preferred_score * w_pref
        + title_score * w_title
        + years_component * w_years
    )

    return MatchResult(
        score=round(score, 1),
        matched_required=matched_req,
        missing_required=missing_req,
        matched_preferred=matched_pref,
        missing_preferred=missing_pref,
        components={
            "required": round(required_score, 1),
            "preferred": round(preferred_score, 1),
            "title": round(title_score, 1),
            "years": round(years_component, 1) if years_score is not None else None,
        },
    )


def compute_match_score(
    profile: ProfileData,
    jd_text: str,
    jd: Optional["JobDescription"] = None,
) -> tuple[float, list[str], list[str]]:
    """
    Compute a weighted keyword/skill match score between profile and JD.

    Returns:
        (score 0-100, matched_keywords, missing_keywords)
    """
    result = compute_match_result(profile, jd_text, jd=jd)
    return result.score, result.matched, result.missing


__all__ = [
    "MatchResult",
    "compute_match_result",
    "compute_match_score",
    "extract_jd_terms",
    "profile_match_corpus",
    "term_in_corpus",
    "profile_years_experience",
    "parse_jd_years_required",
]
