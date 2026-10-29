"""Parse uploaded master resumes into structured ProfileData."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from core.ats_constants import ContactInfo
from core.llm_client import llm_client
from core.profile_schema import ExperienceEntry, ProfileData, SkillCategory


def _extract_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}


def _ensure_entry_ids(entries: list[ExperienceEntry], prefix: str) -> list[ExperienceEntry]:
    result: list[ExperienceEntry] = []
    for index, entry in enumerate(entries):
        data = entry.model_dump()
        if not data.get("id"):
            data["id"] = f"{prefix}-{index + 1}-{uuid.uuid4().hex[:6]}"
        result.append(ExperienceEntry.model_validate(data))
    return result


def _contact_from_dict(raw: dict[str, Any] | None) -> ContactInfo:
    raw = raw or {}
    return ContactInfo(
        name=str(raw.get("name") or raw.get("full_name") or "").strip(),
        email=str(raw.get("email") or "").strip(),
        phone=str(raw.get("phone") or "").strip(),
        location=str(raw.get("location") or "").strip(),
        linkedin=str(raw.get("linkedin") or "").strip(),
        github=str(raw.get("github") or "").strip(),
        portfolio=str(raw.get("portfolio") or "").strip(),
    )


def parse_master_resume(raw_text: str) -> ProfileData:
    """Extract a complete structured profile from multi-page resume text via LLM."""
    if not raw_text or not raw_text.strip():
        raise ValueError("Resume text is empty. Upload a valid PDF, DOCX, or TXT file.")

    prompt = f"""You are extracting a COMPLETE master resume into structured JSON.
Preserve ALL roles, bullets, skills, projects, education, and certifications — do not summarize or drop content.
Return ONLY valid JSON with these fields:
- contact: object with name, email, phone, location, linkedin, github, portfolio (strings)
- summary: string (professional summary / objective)
- skills: array of skill strings (flat list of all skills found)
- skill_categories: array of objects {{"category": string, "items": [strings]}} when categories exist
- experience: array of objects {{"title", "company", "location", "start_date", "end_date", "bullets": [strings]}}
- projects: array of objects with same shape as experience (use title/company for project name/org)
- education: array of objects with same shape (title=degree, company=school)
- certifications: array of strings
- achievements: array of strings

Date format preference: full month names when possible (e.g. "January 2022", "Present").
Use empty string or empty array when a field is missing — never invent content.

Resume text:
{raw_text[:20000]}
"""

    response = llm_client.generate(prompt)
    payload = _extract_json_object(response)
    if not payload:
        raise ValueError("Could not parse resume structure from the uploaded file. Try DOCX or paste more text.")

    contact = _contact_from_dict(payload.get("contact") if isinstance(payload.get("contact"), dict) else {})

    skill_categories: list[SkillCategory] = []
    for item in payload.get("skill_categories") or []:
        if isinstance(item, dict):
            skill_categories.append(SkillCategory.model_validate(item))

    def _parse_entries(key: str) -> list[ExperienceEntry]:
        entries: list[ExperienceEntry] = []
        for item in payload.get(key) or []:
            if isinstance(item, dict):
                entries.append(ExperienceEntry.model_validate(item))
        return entries

    profile = ProfileData(
        contact=contact,
        summary=str(payload.get("summary") or "").strip(),
        skills=[str(s).strip() for s in (payload.get("skills") or []) if str(s).strip()],
        skill_categories=skill_categories,
        experience=_ensure_entry_ids(_parse_entries("experience"), "exp"),
        projects=_ensure_entry_ids(_parse_entries("projects"), "proj"),
        education=_ensure_entry_ids(_parse_entries("education"), "edu"),
        certifications=[str(c).strip() for c in (payload.get("certifications") or []) if str(c).strip()],
        achievements=[str(a).strip() for a in (payload.get("achievements") or []) if str(a).strip()],
    )

    if not profile.contact.name and not profile.experience and not profile.skills:
        raise ValueError("Parsed resume is empty. Check the file content and try again.")

    if not profile.skills and profile.skill_categories:
        flat: list[str] = []
        for cat in profile.skill_categories:
            flat.extend(cat.items)
        profile.skills = flat

    return profile


def profile_from_legacy_fields(
    *,
    full_name: str = "",
    email: str = "",
    phone: str = "",
    location: str = "",
    linkedin: str = "",
    github: str = "",
    portfolio: str = "",
    summary: str = "",
    skills: str = "",
    experience: str = "",
    projects: str = "",
    education: str = "",
    certifications: str = "",
    achievements: str = "",
) -> ProfileData:
    """Build ProfileData from legacy flat text fields (manual form)."""
    skill_list = [p.strip() for p in re.split(r"[,;\n]", skills or "") if p.strip()]
    return ProfileData(
        contact=ContactInfo(
            name=full_name or "",
            email=email or "",
            phone=phone or "",
            location=location or "",
            linkedin=linkedin or "",
            github=github or "",
            portfolio=portfolio or "",
        ),
        summary=summary or "",
        skills=skill_list,
        experience=[
            ExperienceEntry(
                id=f"exp-legacy-{uuid.uuid4().hex[:6]}",
                title="Experience",
                company="",
                bullets=[line.lstrip("-• ").strip() for line in (experience or "").splitlines() if line.strip()],
            )
        ]
        if (experience or "").strip()
        else [],
        projects=[
            ExperienceEntry(
                id=f"proj-legacy-{uuid.uuid4().hex[:6]}",
                title="Projects",
                company="",
                bullets=[line.lstrip("-• ").strip() for line in (projects or "").splitlines() if line.strip()],
            )
        ]
        if (projects or "").strip()
        else [],
        education=[
            ExperienceEntry(
                id=f"edu-legacy-{uuid.uuid4().hex[:6]}",
                title=(education or "").splitlines()[0] if (education or "").strip() else "Education",
                company="",
                bullets=[line.lstrip("-• ").strip() for line in (education or "").splitlines()[1:] if line.strip()],
            )
        ]
        if (education or "").strip()
        else [],
        certifications=[p.strip() for p in re.split(r"[,;\n]", certifications or "") if p.strip()],
        achievements=[p.strip() for p in re.split(r"[,;\n]", achievements or "") if p.strip()],
    )
