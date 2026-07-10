"""Structured job description parsing and prompt formatting."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, field_validator

from core.llm_client import llm_client

if TYPE_CHECKING:
    from db.models import JobDescription


class ParsedJobDescription(BaseModel):
    title: str = ""
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    experience_years: str = ""
    technologies: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    @field_validator(
        "required_skills",
        "preferred_skills",
        "technologies",
        "responsibilities",
        "keywords",
        mode="before",
    )
    @classmethod
    def _coerce_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except json.JSONDecodeError:
                pass
            return [part.strip() for part in re.split(r"[,;\n]", text) if part.strip()]
        return [str(value).strip()]


def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
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


def _serialize_list(values: list[str]) -> str:
    return json.dumps(values)


def _deserialize_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except json.JSONDecodeError:
        pass
    return [part.strip() for part in re.split(r"[,;\n]", value) if part.strip()]


def parse_job_description(raw_text: str) -> ParsedJobDescription:
    """Extract structured fields from a job description via LLM."""
    prompt = f"""You are extracting a structured job description. Use only the supplied text.
Return ONLY valid JSON with these fields:
- title (string)
- required_skills (array of strings)
- preferred_skills (array of strings)
- experience_years (string, e.g. "3-5 years")
- technologies (array of strings)
- responsibilities (array of strings)
- keywords (array of strings — important ATS terms from the JD)

Job Description:
{raw_text}
"""
    llm_output = llm_client.generate(prompt)
    data = _extract_json_object(llm_output)
    if not data:
        return ParsedJobDescription()
    try:
        return ParsedJobDescription.model_validate(data)
    except Exception:
        return ParsedJobDescription()


def parsed_to_db_fields(parsed: ParsedJobDescription) -> dict[str, str]:
    """Map parsed JD to JobDescription column values."""
    return {
        "skills": _serialize_list(parsed.required_skills),
        "preferred_skills": _serialize_list(parsed.preferred_skills),
        "experience": parsed.experience_years,
        "technologies": _serialize_list(parsed.technologies),
        "responsibilities": _serialize_list(parsed.responsibilities),
        "keywords": _serialize_list(parsed.keywords),
    }


def job_description_to_parsed(jd: JobDescription) -> ParsedJobDescription:
    """Reconstruct ParsedJobDescription from a DB record."""
    return ParsedJobDescription(
        title=jd.title or "",
        required_skills=_deserialize_list(jd.skills),
        preferred_skills=_deserialize_list(jd.preferred_skills),
        experience_years=jd.experience or "",
        technologies=_deserialize_list(jd.technologies),
        responsibilities=_deserialize_list(jd.responsibilities),
        keywords=_deserialize_list(jd.keywords),
    )


def format_jd_for_prompt(jd: JobDescription) -> str:
    """Build a prompt-friendly JD block with priority keywords first."""
    parsed = job_description_to_parsed(jd)
    sections: list[str] = []

    if jd.title:
        sections.append(f"Title: {jd.title}")
    if parsed.required_skills:
        sections.append("Required Skills: " + ", ".join(parsed.required_skills))
    if parsed.preferred_skills:
        sections.append("Preferred Skills: " + ", ".join(parsed.preferred_skills))
    if parsed.technologies:
        sections.append("Technologies: " + ", ".join(parsed.technologies))
    if parsed.keywords:
        sections.append("Priority Keywords: " + ", ".join(parsed.keywords))
    if parsed.experience_years:
        sections.append(f"Experience: {parsed.experience_years}")
    if parsed.responsibilities:
        sections.append("Responsibilities:\n- " + "\n- ".join(parsed.responsibilities))
    if jd.raw_text:
        sections.append(f"Full Job Description:\n{jd.raw_text}")

    return "\n\n".join(sections)


def get_priority_keywords(jd: JobDescription, limit: int = 10) -> list[str]:
    """Return top priority keywords/skills for refinement prompts."""
    parsed = job_description_to_parsed(jd)
    seen: set[str] = set()
    priority: list[str] = []
    for term in (
        parsed.required_skills
        + parsed.technologies
        + parsed.keywords
        + parsed.preferred_skills
    ):
        key = term.lower()
        if key not in seen:
            seen.add(key)
            priority.append(term)
        if len(priority) >= limit:
            break
    return priority
