"""Tests for deterministic weighted match scorer."""

from __future__ import annotations

import json

from core.ats_constants import ContactInfo
from core.matcher import (
    compute_match_result,
    compute_match_score,
    extract_jd_terms,
    parse_jd_years_required,
    profile_match_corpus,
    profile_years_experience,
    term_in_corpus,
)
from core.profile_schema import ExperienceEntry, ProfileData


class FakeJD:
    def __init__(
        self,
        *,
        title: str = "",
        skills: list[str] | None = None,
        preferred_skills: list[str] | None = None,
        technologies: list[str] | None = None,
        keywords: list[str] | None = None,
        experience: str = "",
        raw_text: str = "",
    ) -> None:
        self.title = title
        self.skills = json.dumps(skills or [])
        self.preferred_skills = json.dumps(preferred_skills or [])
        self.technologies = json.dumps(technologies or [])
        self.keywords = json.dumps(keywords or [])
        self.experience = experience
        self.raw_text = raw_text
        self.responsibilities = json.dumps([])


def _base_profile(**kwargs) -> ProfileData:
    defaults = dict(
        contact=ContactInfo(name="Ada Lovelace", email="ada@example.com", location="Seattle"),
        summary="Software engineer with Python and SQL experience.",
        skills=["Python", "SQL", "AWS", "REST APIs"],
        experience=[
            ExperienceEntry(
                id="exp-1",
                title="Backend Engineer",
                company="Acme",
                start_date="January 2020",
                end_date="Present",
                bullets=["Built APIs with Python and SQL", "Deployed services on AWS"],
            ),
        ],
    )
    defaults.update(kwargs)
    return ProfileData(**defaults)


def test_match_score_prefers_overlapping_skills() -> None:
    profile = _base_profile()
    jd = FakeJD(
        title="Backend Engineer",
        skills=["Python", "SQL", "Kubernetes"],
        experience="3+ years",
    )
    result = compute_match_result(profile, "", jd=jd)
    assert result.score > 0
    assert result.score < 100  # Kubernetes missing
    assert any("python" in m.lower() for m in result.matched_required)
    assert any("kubernetes" in m.lower() for m in result.missing_required)


def test_empty_jd_returns_zero() -> None:
    profile = _base_profile()
    score, matched, missing = compute_match_score(profile, "")
    assert score == 0.0
    assert matched == []
    assert missing == []


def test_alias_js_matches_javascript() -> None:
    profile = _base_profile(skills=["JS", "Python"])
    jd = FakeJD(skills=["JavaScript", "Python"])
    result = compute_match_result(profile, "", jd=jd)
    assert any("javascript" in m.lower() for m in result.matched_required)
    assert not any("javascript" in m.lower() for m in result.missing_required)


def test_no_java_false_positive_from_javascript() -> None:
    profile = _base_profile(skills=["JavaScript", "React"], summary="Frontend engineer")
    jd = FakeJD(skills=["Java"])
    result = compute_match_result(profile, "", jd=jd)
    assert "Java" in result.missing_required or any(
        m.lower() == "java" for m in result.missing_required
    )
    assert not any(m.lower() == "java" for m in result.matched_required)


def test_fallback_keeps_tech_tokens_and_drops_stopwords() -> None:
    buckets = extract_jd_terms(
        None,
        "We need C# and Node.js experience for the role and the team",
    )
    lower = [t.lower() for t in buckets.required]
    assert any("c#" in t or t == "c#" for t in lower)
    assert any("node" in t for t in lower)
    assert "the" not in lower
    assert "and" not in lower
    assert "for" not in lower


def test_required_miss_hurts_more_than_preferred_miss() -> None:
    profile = _base_profile(skills=["Python"])
    # Same single miss in required vs preferred
    jd_req = FakeJD(skills=["Python", "Kubernetes"], preferred_skills=[])
    jd_pref = FakeJD(skills=["Python"], preferred_skills=["Kubernetes"])
    score_req = compute_match_result(profile, "", jd=jd_req).score
    score_pref = compute_match_result(profile, "", jd=jd_pref).score
    assert score_pref > score_req


def test_years_adequate_does_not_tank() -> None:
    # ~6 years from Jan 2020 to ~Sep 2026
    profile = _base_profile(
        experience=[
            ExperienceEntry(
                id="e1",
                title="Engineer",
                company="Acme",
                start_date="January 2020",
                end_date="Present",
                bullets=["Built systems"],
            )
        ]
    )
    assert profile_years_experience(profile) is not None
    assert profile_years_experience(profile) >= 5.0
    jd = FakeJD(skills=["Python"], experience="5+ years", title="Engineer")
    result = compute_match_result(profile, "", jd=jd)
    assert result.components.get("years") == 100.0 or result.components.get("years") is None
    # With parseable years, should be full credit
    assert parse_jd_years_required("5+ years") == 5.0
    assert result.components["years"] == 100.0


def test_years_shortfall_lowers_score() -> None:
    profile = _base_profile(
        skills=["Python"],
        experience=[
            ExperienceEntry(
                id="e1",
                title="Engineer",
                company="Acme",
                start_date="January 2025",
                end_date="Present",
                bullets=["Built systems"],
            )
        ],
    )
    years = profile_years_experience(profile)
    assert years is not None and years < 3.0
    jd = FakeJD(skills=["Python"], experience="7+ years", title="Engineer")
    result = compute_match_result(profile, "", jd=jd)
    assert result.components["years"] is not None
    assert result.components["years"] < 50.0


def test_contact_location_does_not_inflate_match() -> None:
    profile = ProfileData(
        contact=ContactInfo(name="Ada", email="a@b.com", location="Kubernetes Valley"),
        summary="Software engineer.",
        skills=["Python"],
        experience=[],
    )
    corpus = profile_match_corpus(profile)
    assert not term_in_corpus("Kubernetes", corpus)
    jd = FakeJD(skills=["Kubernetes"])
    result = compute_match_result(profile, "", jd=jd)
    assert any("kubernetes" in m.lower() for m in result.missing_required)


def test_get_priority_keywords_limit_not_applied_to_scoring() -> None:
    skills = [f"Skill{i}" for i in range(15)]
    jd = FakeJD(skills=skills)
    buckets = extract_jd_terms(jd, "")
    assert len(buckets.required) == 15
