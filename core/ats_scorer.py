from __future__ import annotations

import re
from typing import TYPE_CHECKING, List, Tuple

from core.ats_constants import (
    DATE_PATTERN,
    REQUIRED_SECTIONS,
    SINGLE_DATE_PATTERN,
    normalize_section_heading,
)
from core.jd_parser import _deserialize_list
from core.llm_client import llm_client

if TYPE_CHECKING:
    from db.models import JobDescription

STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with",
    "by", "from", "as", "is", "was", "are", "were", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "must",
    "shall", "can", "need", "our", "your", "their", "this", "that", "these", "those", "we",
    "you", "they", "it", "its", "who", "which", "what", "when", "where", "why", "how", "all",
    "each", "every", "both", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "just", "also", "into", "over",
    "such", "about", "above", "after", "before", "between", "during", "under", "again",
    "further", "then", "once", "here", "there", "any", "if", "while", "through", "work",
    "working", "role", "job", "position", "candidate", "team", "company", "experience",
    "years", "year", "ability", "able", "including", "etc", "using", "use", "used",
})

_SECTION_SEARCH_TERMS = {
    "Professional Summary": ["profile", "professional summary", "summary"],
    "Skills": ["skill", "skills"],
    "Work Experience": ["work experience", "experience"],
    "Education": ["education"],
    "Certifications": ["certifications"],
}


def validate_ats_format(resume_text: str) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    lines = [line.strip() for line in resume_text.splitlines() if line.strip()]

    if any("|" in line and ("---" in line or line.count("|") >= 2) for line in lines):
        reasons.append("Resume contains a markdown table, which is not ATS-friendly.")

    layout_keywords = ["two-column", "multicolumn", "display: flex", "display: grid"]
    if any(keyword in resume_text.lower() for keyword in layout_keywords):
        reasons.append("Resume appears to use a multi-column layout, which can break ATS parsing.")

    heading_pattern = re.compile(r"^#{1,3}\s+(.+)$")
    found_canonical: set[str] = set()
    for line in lines:
        match = heading_pattern.match(line)
        if match:
            canonical = normalize_section_heading(match.group(1))
            if canonical:
                found_canonical.add(canonical)

    missing = [heading for heading in REQUIRED_SECTIONS if heading not in found_canonical]
    if missing:
        reasons.append(f"Missing standard heading(s): {', '.join(missing)}")

    # Check date format on lines with pipe separators in experience/education context
    for line in lines:
        if "|" in line and not line.startswith("#"):
            date_part = line.split("|", 1)[-1].strip()
            if date_part and re.search(r"\d{4}", date_part) and not (
                DATE_PATTERN.search(date_part) or SINGLE_DATE_PATTERN.search(date_part)
            ):
                reasons.append(
                    f"Date must use full month name format (Month Year - Month Year): {date_part}"
                )
                break

    return not reasons, reasons


def _tokenize(text: str) -> list[str]:
    terms = re.findall(r"[a-zA-Z0-9+#.-]+", text.lower())
    return [term for term in terms if len(term) > 2 and term not in STOP_WORDS]


def _priority_terms_from_jd(jd: JobDescription | None) -> list[str]:
    if jd is None:
        return []
    terms: list[str] = []
    seen: set[str] = set()
    for field_value in (jd.skills, jd.technologies, jd.keywords, jd.preferred_skills):
        for term in _deserialize_list(field_value):
            for token in _tokenize(term):
                if token not in seen:
                    seen.add(token)
                    terms.append(token)
    return terms


def score_resume(
    resume_text: str,
    jd_text: str,
    jd: JobDescription | None = None,
) -> Tuple[float, str, List[str]]:
    resume_lower = resume_text.lower()
    jd_terms = _tokenize(jd_text)
    priority_terms = _priority_terms_from_jd(jd)

    keyword_hits = [term for term in set(jd_terms) if term in resume_lower]
    priority_hits = [term for term in priority_terms if term in resume_lower]

    generic_score = (len(keyword_hits) / max(len(set(jd_terms)), 1)) * 60.0
    priority_score = (len(priority_hits) / max(len(priority_terms), 1)) * 40.0 if priority_terms else 0.0
    keyword_density = round(min(100.0, generic_score + priority_score), 1)

    section_presence = 0
    for section, search_terms in _SECTION_SEARCH_TERMS.items():
        if any(term in resume_lower for term in search_terms):
            section_presence += 20

    qualitative_prompt = f"""
Review the candidate resume below against the job description. Use only the resume text and job description text supplied. Provide a short qualitative assessment and a list of missing keywords.
Resume:
{resume_text}

Job Description:
{jd_text}
"""
    qualitative = llm_client.generate(qualitative_prompt)

    missing_source = priority_terms if priority_terms else list(set(jd_terms))
    missing_keywords = [term for term in missing_source if term not in resume_lower][:10]

    ats_score = round(min(100.0, keyword_density + section_presence * 0.5), 1)
    summary = qualitative[:400]
    return ats_score, summary, missing_keywords


__all__ = [
    "validate_ats_format",
    "score_resume",
]
