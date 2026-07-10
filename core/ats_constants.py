"""Shared ATS formatting constants and markdown normalization."""

from __future__ import annotations

import re
from dataclasses import dataclass

CANONICAL_SECTIONS: list[str] = [
    "Professional Summary",
    "Skills",
    "Work Experience",
    "Education",
    "Certifications",
]

PDF_SECTION_DISPLAY: dict[str, str] = {
    "Professional Summary": "PROFESSIONAL SUMMARY",
    "Skills": "SKILLS",
    "Work Experience": "WORK EXPERIENCE",
    "Education": "EDUCATION",
    "Certifications": "CERTIFICATIONS",
}

PDF_SECTION_SEARCH_TERMS: dict[str, list[str]] = {
    "Professional Summary": ["profile", "professional summary"],
    "Skills": ["skill", "skills"],
    "Work Experience": ["work experience", "experience"],
    "Education": ["education"],
    "Certifications": ["certifications"],
}

REQUIRED_SECTIONS: list[str] = [
    "Professional Summary",
    "Skills",
    "Work Experience",
    "Education",
]

SECTION_ALIASES: dict[str, str] = {
    "summary": "Professional Summary",
    "professional summary": "Professional Summary",
    "profile": "Professional Summary",
    "objective": "Professional Summary",
    "skills": "Skills",
    "skill": "Skills",
    "technical skills": "Skills",
    "experience": "Work Experience",
    "work experience": "Work Experience",
    "employment": "Work Experience",
    "employment history": "Work Experience",
    "education": "Education",
    "certifications": "Certifications",
    "certification": "Certifications",
}

MONTH_NAMES = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
)

DATE_PATTERN = re.compile(
    rf"(?:{MONTH_NAMES})\s+\d{{4}}\s*-\s*(?:Present|(?:{MONTH_NAMES})\s+\d{{4}})",
    re.IGNORECASE,
)

SINGLE_DATE_PATTERN = re.compile(
    rf"(?:{MONTH_NAMES})\s+\d{{4}}",
    re.IGNORECASE,
)

BAD_DATE_PATTERN = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\b|\b\d{4}\s*-\s*\d{4}\b",
    re.IGNORECASE,
)

HEADING_LINE_PATTERN = re.compile(r"^#{1,3}\s+(.+)$")

KEYWORD_COVERAGE_THRESHOLD = 0.70


@dataclass
class ContactInfo:
    name: str = ""
    location: str = ""
    phone: str = ""
    email: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""


def normalize_section_heading(text: str) -> str | None:
    """Map a heading string to its canonical section name, or None if not a section."""
    key = text.strip().lower().rstrip(":")
    return SECTION_ALIASES.get(key)


def normalize_linkedin_url(url: str) -> str:
    """Ensure LinkedIn URL has https:// prefix."""
    url = url.strip()
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"https://{url.lstrip('/')}"


def _parse_sections(markdown: str) -> dict[str, list[str]]:
    """Split markdown into canonical section -> content lines."""
    sections: dict[str, list[str]] = {}
    current: str | None = None

    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            if current is not None:
                sections.setdefault(current, []).append("")
            continue

        if stripped.startswith("#"):
            match = HEADING_LINE_PATTERN.match(stripped)
            if match:
                heading_text = match.group(1).strip()
                canonical = normalize_section_heading(heading_text)
                if canonical:
                    current = canonical
                    sections.setdefault(current, [])
                    continue

        if current is not None:
            sections.setdefault(current, []).append(line.rstrip())
        elif stripped.startswith("#"):
            continue
        else:
            sections.setdefault("_preamble", []).append(line.rstrip())

    return sections


def reorder_and_normalize_markdown(markdown: str) -> str:
    """Normalize section headings and reorder to canonical ATS order."""
    sections = _parse_sections(markdown)
    parts: list[str] = []

    for section_name in CANONICAL_SECTIONS:
        lines = sections.get(section_name, [])
        content_lines = [ln for ln in lines if ln.strip()]
        if not content_lines and section_name == "Certifications":
            continue
        if not content_lines:
            continue
        parts.append(f"## {section_name}")
        parts.extend(lines)
        if lines and lines[-1].strip():
            parts.append("")

    if not parts:
        return markdown.strip()

    return "\n".join(parts).strip() + "\n"


def section_heading_positions(text: str) -> dict[str, int]:
    """Return canonical section -> first character index in text."""
    positions: dict[str, int] = {}
    lower = text.lower()
    offset = 0
    for line in lower.splitlines(keepends=True):
        heading = re.sub(r"[^a-z\s]", "", line).strip()
        for section in CANONICAL_SECTIONS:
            if section in positions:
                continue
            search_terms = PDF_SECTION_SEARCH_TERMS.get(section, [section.lower()])
            if heading in search_terms:
                positions[section] = offset + line.lower().find(heading)
        offset += len(line)

    if positions:
        return positions

    for section in CANONICAL_SECTIONS:
        search_terms = PDF_SECTION_SEARCH_TERMS.get(section, [section.lower()])
        best_idx = -1
        for term in search_terms:
            idx = lower.find(term)
            if idx >= 0 and (best_idx < 0 or idx < best_idx):
                best_idx = idx
        if best_idx >= 0:
            positions[section] = best_idx
    return positions


def sections_in_reading_order(text: str) -> bool:
    """Check that canonical sections appear in the correct top-to-bottom order."""
    positions = section_heading_positions(text)
    found = [positions[s] for s in CANONICAL_SECTIONS if s in positions]
    return found == sorted(found)
