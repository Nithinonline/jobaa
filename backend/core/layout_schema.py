"""Pydantic v2 schemas for master resume layout extraction and spatial budgeting."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from core.template_config import TemplateConfig


class FontSpec(BaseModel):
    name: str = "Helvetica"
    size_pt: float = 10.0
    color_hex: str = "#000000"
    bold: bool = False
    italic: bool = False


class SpacingSpec(BaseModel):
    margin_top_inches: float = 0.4
    margin_bottom_inches: float = 0.4
    margin_left_inches: float = 0.5
    margin_right_inches: float = 0.5
    section_gap_inches: float = 0.04
    line_spacing: float = 1.15
    paragraph_after_pt: float = 3.0


class EntryBudget(BaseModel):
    max_bullets: int = 3
    char_budget_per_bullet: int = 140
    max_total_chars: int = 420


class LayoutBudget(BaseModel):
    target_page_count: int = 1
    max_summary_chars: int = 320
    max_skills_lines: int = 4
    experience_budgets: dict[int, EntryBudget] = Field(default_factory=dict)
    project_budgets: dict[int, EntryBudget] = Field(default_factory=dict)

    def to_prompt_instructions(self) -> str:
        lines = [
            f"STRICT 1-PAGE SPATIAL BUDGET (Target: {self.target_page_count} page):",
            f"- Professional Summary: max {self.max_summary_chars} characters total.",
            f"- Skills: limit to {self.max_skills_lines} concise category lines.",
        ]
        if self.experience_budgets:
            lines.append("- Experience entries budget:")
            for idx, budget in sorted(self.experience_budgets.items()):
                lines.append(
                    f"  * Entry {idx}: select at most {budget.max_bullets} bullets (each <= {budget.char_budget_per_bullet} characters)."
                )
        if self.project_budgets:
            lines.append("- Project entries budget:")
            for idx, budget in sorted(self.project_budgets.items()):
                lines.append(
                    f"  * Project {idx}: select at most {budget.max_bullets} bullets (each <= {budget.char_budget_per_bullet} characters)."
                )
        lines.append(
            "- Selections that exceed these limits cause line-wrapping and will be rejected."
        )
        return "\n".join(lines)


class SectionSlot(BaseModel):
    canonical_section: str
    original_heading_text: str = ""
    entry_count: int = 0
    bullets_per_entry: list[int] = Field(default_factory=list)
    avg_bullet_chars: int = 130
    max_bullet_chars: int = 180


class MasterLayoutProfile(BaseModel):
    file_format: str = "pdf"
    page_count: int = 1
    page_size: str = "A4"
    is_two_column: bool = False
    column_split_ratio: float = 0.35  # Left column ratio if two-column
    primary_color: str = "#1f497d"
    secondary_color: str = "#333333"
    heading_font_family: str = "Helvetica"
    body_font_family: str = "Helvetica"
    name_font_size: float = 18.0
    heading_font_size: float = 11.5
    body_font_size: float = 9.2
    title_font_size: float = 10.5
    skill_font_size: float = 8.8
    contact_separator: str = " | "
    spacing: SpacingSpec = Field(default_factory=SpacingSpec)
    section_order: list[str] = Field(
        default_factory=lambda: [
            "Professional Summary",
            "Skills",
            "Work Experience",
            "Education",
            "Certifications",
        ]
    )
    section_headings: dict[str, str] = Field(default_factory=dict)
    section_slots: dict[str, SectionSlot] = Field(default_factory=dict)

    def to_template_config(self) -> TemplateConfig:
        headings = self.section_headings or {
            "Professional Summary": "PROFESSIONAL SUMMARY",
            "Skills": "SKILLS",
            "Work Experience": "EXPERIENCE",
            "Education": "EDUCATION",
            "Certifications": "CERTIFICATIONS",
        }
        return TemplateConfig(
            section_order=list(self.section_order),
            section_headings=headings,
            primary_color=self.primary_color,
            secondary_color=self.secondary_color,
            font_family=self.body_font_family,
            name_font_size=self.name_font_size,
            heading_font_size=self.heading_font_size,
            body_font_size=self.body_font_size,
            title_font_size=self.title_font_size,
            skill_font_size=self.skill_font_size,
            contact_separator=self.contact_separator,
            margin_inches=self.spacing.margin_left_inches,
            top_margin_inches=self.spacing.margin_top_inches,
            bottom_margin_inches=self.spacing.margin_bottom_inches,
            section_gap_inches=self.spacing.section_gap_inches,
            page_size=self.page_size,
        )

    def derive_layout_budget(self) -> LayoutBudget:
        budget = LayoutBudget(
            target_page_count=max(1, self.page_count),
            max_summary_chars=320 if self.page_count == 1 else 500,
            max_skills_lines=4,
        )
        exp_slot = self.section_slots.get("Work Experience")
        if exp_slot and exp_slot.bullets_per_entry:
            for idx, count in enumerate(exp_slot.bullets_per_entry):
                max_b = max(1, min(count, 4))
                char_b = min(160, max(100, exp_slot.avg_bullet_chars or 130))
                budget.experience_budgets[idx] = EntryBudget(
                    max_bullets=max_b,
                    char_budget_per_bullet=char_b,
                    max_total_chars=max_b * char_b,
                )
        else:
            # Fallback default 1-page budget for up to 5 roles
            for idx in range(5):
                max_b = 3 if idx == 0 else 2
                budget.experience_budgets[idx] = EntryBudget(
                    max_bullets=max_b,
                    char_budget_per_bullet=135,
                    max_total_chars=max_b * 135,
                )

        proj_slot = self.section_slots.get("Projects")
        if proj_slot and proj_slot.bullets_per_entry:
            for idx, count in enumerate(proj_slot.bullets_per_entry):
                max_b = max(1, min(count, 3))
                budget.project_budgets[idx] = EntryBudget(
                    max_bullets=max_b,
                    char_budget_per_bullet=120,
                    max_total_chars=max_b * 120,
                )
        return budget


def master_layout_profile_from_json(raw: str | None) -> MasterLayoutProfile:
    if not raw or not raw.strip():
        return MasterLayoutProfile()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return MasterLayoutProfile.model_validate(data)
    except (json.JSONDecodeError, ValueError):
        pass
    return MasterLayoutProfile()
