"""Deterministic resume Markdown assembly from structured ProfileData."""

from __future__ import annotations

from core.ats_constants import CANONICAL_SECTIONS
from core.profile_schema import ProfileData
from core.template_config import TemplateConfig


def _skills_lines(profile: ProfileData) -> list[str]:
    lines: list[str] = []
    if profile.skill_categories:
        for cat in profile.skill_categories:
            items = [i for i in (cat.items or []) if i.strip()]
            if items:
                lines.append(f"- {cat.category} : {', '.join(items)}")
    if not lines and profile.skills:
        # Bucket flat skills into a Technical line
        lines.append(f"- Technical : {', '.join(profile.skills)}")
    return lines


def _entry_block(entry_title: str, company: str, location: str | None, start: str, end: str, bullets: list[str]) -> str:
    parts: list[str] = [f"### {entry_title}"]
    meta_bits = [b for b in [company, location] if b]
    date_range = " - ".join(p for p in [start, end] if p) or ""
    if meta_bits or date_range:
        left = ", ".join(meta_bits)
        if left and date_range:
            parts.append(f"{left} | {date_range}")
        elif date_range:
            parts.append(date_range)
        else:
            parts.append(left)
    for bullet in bullets:
        if bullet.strip():
            parts.append(f"- {bullet.strip()}")
    return "\n".join(parts)


_SECTION_BUILDERS = {
    "Professional Summary": lambda p: (p.summary or "").strip(),
    "Skills": lambda p: "\n".join(_skills_lines(p)),
    "Work Experience": lambda p: "\n\n".join(
        _entry_block(e.title, e.company, e.location, e.start_date, e.end_date, e.bullets)
        for e in p.experience
    ),
    "Projects": lambda p: "\n\n".join(
        _entry_block(e.title, e.company, e.location, e.start_date, e.end_date, e.bullets)
        for e in p.projects
    ),
    "Education": lambda p: "\n\n".join(
        _entry_block(e.title, e.company, e.location, e.start_date, e.end_date, e.bullets)
        for e in p.education
    ),
    "Certifications": lambda p: "\n".join(f"- {c}" for c in (p.certifications or []) if c.strip()),
    "Achievements": lambda p: "\n".join(f"- {a}" for a in (p.achievements or []) if a.strip()),
}


def assemble_resume_markdown(
    profile: ProfileData,
    *,
    section_order: list[str] | None = None,
    template_config: TemplateConfig | None = None,
) -> str:
    """
    Build ATS-friendly Markdown from structured profile data.
    Contact is omitted (added by the PDF exporter).
    """
    order = list(section_order or [])
    if not order and template_config is not None:
        order = list(template_config.section_order or [])
    if not order:
        order = list(CANONICAL_SECTIONS)

    # Normalize aliases to canonical names used by builders
    alias = {
        "summary": "Professional Summary",
        "professional summary": "Professional Summary",
        "skills": "Skills",
        "experience": "Work Experience",
        "work experience": "Work Experience",
        "projects": "Projects",
        "education": "Education",
        "certifications": "Certifications",
        "achievements": "Achievements",
    }
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in order:
        key = alias.get(raw.strip().lower(), raw.strip())
        if key in _SECTION_BUILDERS and key not in seen:
            normalized.append(key)
            seen.add(key)
    for key in CANONICAL_SECTIONS:
        if key not in seen and key in _SECTION_BUILDERS:
            # Only append optional sections if they have content later
            if key in ("Certifications", "Achievements", "Projects"):
                continue
            normalized.append(key)
            seen.add(key)

    # Ensure optional sections with content appear
    for optional in ("Projects", "Certifications", "Achievements"):
        if optional not in seen:
            body_fn = _SECTION_BUILDERS[optional]
            if body_fn(profile).strip():
                # Insert before Education if present, else append
                if "Education" in normalized:
                    idx = normalized.index("Education")
                    normalized.insert(idx, optional)
                else:
                    normalized.append(optional)

    sections: list[str] = []
    for heading in normalized:
        body = _SECTION_BUILDERS[heading](profile).strip()
        if not body:
            if heading in ("Certifications", "Achievements", "Projects"):
                continue
            # Keep required empty-ish sections only if they have something
            continue
        sections.append(f"## {heading}\n{body}")

    return "\n\n".join(sections).strip() + "\n"
