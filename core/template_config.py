"""Resume visual template config (leaf module — no project circular deps)."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field


class TemplateConfig(BaseModel):
    section_order: list[str] = Field(
        default_factory=lambda: [
            "Professional Summary",
            "Skills",
            "Work Experience",
            "Education",
            "Certifications",
        ]
    )
    section_headings: dict[str, str] = Field(
        default_factory=lambda: {
            "Professional Summary": "PROFESSIONAL SUMMARY",
            "Skills": "SKILLS",
            "Work Experience": "EXPERIENCE",
            "Education": "EDUCATION",
            "Certifications": "CERTIFICATIONS",
        }
    )
    primary_color: str = "#365f7f"
    font_family: str = "Times-Roman"
    name_font_size: float = 18.0
    heading_font_size: float = 11.0
    body_font_size: float = 9.2
    title_font_size: float = 10.8
    skill_font_size: float = 8.8
    contact_separator: str = " | "
    use_icon_labels: bool = False
    margin_inches: float = 0.5
    section_rule_thickness: float = 1.2
    section_gap_inches: float = 0.03


def template_config_from_json(raw: str | None) -> TemplateConfig:
    if not raw or not raw.strip():
        return TemplateConfig()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return TemplateConfig.model_validate(data)
    except (json.JSONDecodeError, ValueError):
        pass
    return TemplateConfig()
