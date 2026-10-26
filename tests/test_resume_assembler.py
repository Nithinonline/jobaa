"""Tests for deterministic resume assembler."""

from __future__ import annotations

from core.ats_constants import ContactInfo
from core.profile_schema import ExperienceEntry, ProfileData, SkillCategory
from core.resume_assembler import assemble_resume_markdown
from core.template_config import TemplateConfig


def _profile() -> ProfileData:
    return ProfileData(
        contact=ContactInfo(name="Ada Lovelace", email="ada@example.com"),
        summary="Engineer with Python experience.",
        skills=["Python", "SQL"],
        skill_categories=[SkillCategory(category="Technical", items=["Python", "SQL"])],
        experience=[
            ExperienceEntry(
                id="exp-1",
                title="Backend Engineer",
                company="Acme",
                location="Seattle",
                start_date="January 2022",
                end_date="Present",
                bullets=["Built APIs"],
            )
        ],
        education=[
            ExperienceEntry(
                id="edu-1",
                title="B.S. Computer Science",
                company="State U",
                start_date="May 2018",
                end_date="May 2018",
            )
        ],
        certifications=["AWS SAA"],
    )


def test_assembler_respects_section_order() -> None:
    md = assemble_resume_markdown(
        _profile(),
        section_order=["Skills", "Professional Summary", "Work Experience", "Education"],
    )
    skills_idx = md.index("## Skills")
    summary_idx = md.index("## Professional Summary")
    assert skills_idx < summary_idx


def test_assembler_includes_allowed_skills_only_from_profile() -> None:
    md = assemble_resume_markdown(_profile())
    assert "Python" in md
    assert "SQL" in md
    assert "## Work Experience" in md
    assert "Acme" in md
    assert "AWS SAA" in md


def test_assembler_uses_template_config_order() -> None:
    cfg = TemplateConfig(section_order=["Education", "Skills", "Work Experience", "Professional Summary"])
    md = assemble_resume_markdown(_profile(), template_config=cfg)
    assert md.index("## Education") < md.index("## Skills")
