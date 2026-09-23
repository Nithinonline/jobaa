"""Structured profile schemas for master resume handling."""

from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from core.ats_constants import ContactInfo
from core.proposals import (  # re-export
    ProposalStatus,
    ProposalType,
    ProposedChange,
    proposals_from_json,
)
from core.template_config import TemplateConfig, template_config_from_json  # re-export

__all__ = [
    "ExperienceEntry",
    "SkillCategory",
    "ProfileData",
    "TemplateConfig",
    "ProposalType",
    "ProposalStatus",
    "ProposedChange",
    "profile_data_from_json",
    "template_config_from_json",
    "proposals_from_json",
]


class ExperienceEntry(BaseModel):
    id: str = ""
    title: str = ""
    company: str = ""
    location: Optional[str] = None
    start_date: str = ""
    end_date: str = ""
    bullets: list[str] = Field(default_factory=list)

    @field_validator("bullets", mode="before")
    @classmethod
    def _coerce_bullets(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [part.strip() for part in value.split("\n") if part.strip()]
        return [str(value).strip()]


class SkillCategory(BaseModel):
    category: str = "Technical"
    items: list[str] = Field(default_factory=list)

    @field_validator("items", mode="before")
    @classmethod
    def _coerce_items(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [part.strip() for part in value.replace("\n", ",").split(",") if part.strip()]
        return [str(value).strip()]


class ProfileData(BaseModel):
    contact: ContactInfo = Field(default_factory=ContactInfo)
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    skill_categories: list[SkillCategory] = Field(default_factory=list)
    experience: list[ExperienceEntry] = Field(default_factory=list)
    projects: list[ExperienceEntry] = Field(default_factory=list)
    education: list[ExperienceEntry] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)

    @field_validator("skills", "certifications", "achievements", mode="before")
    @classmethod
    def _coerce_str_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [part.strip() for part in value.replace("\n", ",").split(",") if part.strip()]
        return [str(value).strip()]

    def all_skill_tokens(self) -> set[str]:
        tokens: set[str] = set()
        for skill in self.skills:
            tokens.add(skill.lower().strip())
        for category in self.skill_categories:
            for item in category.items:
                tokens.add(item.lower().strip())
        return {t for t in tokens if t}

    def to_prompt_text(self) -> str:
        """Serialize profile into a text block for LLM prompts."""
        sections: list[str] = []
        contact_parts: list[str] = []
        c = self.contact
        if c.name:
            contact_parts.append(f"Name: {c.name}")
        if c.email:
            contact_parts.append(f"Email: {c.email}")
        if c.phone:
            contact_parts.append(f"Phone: {c.phone}")
        if c.location:
            contact_parts.append(f"Location: {c.location}")
        if c.linkedin:
            contact_parts.append(f"LinkedIn: {c.linkedin}")
        if c.github:
            contact_parts.append(f"GitHub: {c.github}")
        if c.portfolio:
            contact_parts.append(f"Portfolio: {c.portfolio}")
        if contact_parts:
            sections.append("Contact:\n" + "\n".join(contact_parts))
        if self.summary:
            sections.append(f"Summary:\n{self.summary}")
        if self.skill_categories:
            skill_lines = [
                f"- {cat.category} : {', '.join(cat.items)}"
                for cat in self.skill_categories
                if cat.items
            ]
            if skill_lines:
                sections.append("Skills:\n" + "\n".join(skill_lines))
        elif self.skills:
            sections.append("Skills:\n" + ", ".join(self.skills))
        for label, entries in [
            ("Experience", self.experience),
            ("Projects", self.projects),
            ("Education", self.education),
        ]:
            if not entries:
                continue
            blocks: list[str] = []
            for entry in entries:
                header = f"{entry.title} at {entry.company}".strip()
                if entry.id:
                    header = f"[{entry.id}] {header}"
                date_line = f"{entry.start_date} - {entry.end_date}".strip(" -")
                loc = f", {entry.location}" if entry.location else ""
                lines = [header, f"{date_line}{loc}".strip()]
                for bullet in entry.bullets:
                    lines.append(f"- {bullet}")
                blocks.append("\n".join(lines))
            sections.append(f"{label}:\n" + "\n\n".join(blocks))
        if self.certifications:
            sections.append("Certifications:\n" + "\n".join(f"- {c}" for c in self.certifications))
        if self.achievements:
            sections.append("Achievements:\n" + "\n".join(f"- {a}" for a in self.achievements))
        return "\n\n".join(sections)

    def to_flat_fields(self) -> dict[str, str]:
        """Map structured profile back to legacy Profile text columns."""
        skills_text = ""
        if self.skill_categories:
            skills_text = "\n".join(
                f"{cat.category}: {', '.join(cat.items)}" for cat in self.skill_categories if cat.items
            )
        elif self.skills:
            skills_text = ", ".join(self.skills)

        def _entries_to_text(entries: list[ExperienceEntry]) -> str:
            blocks: list[str] = []
            for entry in entries:
                lines = [
                    f"{entry.title}",
                    f"{entry.company}{', ' + entry.location if entry.location else ''} | {entry.start_date} - {entry.end_date}".strip(" |"),
                ]
                lines.extend(f"- {b}" for b in entry.bullets)
                blocks.append("\n".join(lines))
            return "\n\n".join(blocks)

        return {
            "full_name": self.contact.name or "",
            "email": self.contact.email or "",
            "phone": self.contact.phone or "",
            "location": self.contact.location or "",
            "linkedin": self.contact.linkedin or "",
            "github": self.contact.github or "",
            "portfolio": self.contact.portfolio or "",
            "summary": self.summary or "",
            "skills": skills_text,
            "experience": _entries_to_text(self.experience),
            "projects": _entries_to_text(self.projects),
            "education": _entries_to_text(self.education),
            "certifications": "\n".join(self.certifications),
            "achievements": "\n".join(self.achievements),
        }


def profile_data_from_json(raw: str | None) -> ProfileData | None:
    if not raw or not raw.strip():
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            contact = data.get("contact")
            if isinstance(contact, dict):
                data["contact"] = ContactInfo(
                    name=contact.get("name", "") or "",
                    email=contact.get("email", "") or "",
                    phone=contact.get("phone", "") or "",
                    location=contact.get("location", "") or "",
                    linkedin=contact.get("linkedin", "") or "",
                    github=contact.get("github", "") or "",
                    portfolio=contact.get("portfolio", "") or "",
                )
            return ProfileData.model_validate(data)
    except (json.JSONDecodeError, ValueError):
        return None
    return None
