"""Tests for profile schema, diff, matcher, template extractor, and agent helpers."""

from __future__ import annotations

from core.ats_constants import ContactInfo
from core.matcher import compute_match_score
from core.profile_diff import (
    annotate_proposal_groundedness,
    skill_in_profile,
    text_grounded_in_profile,
)
from core.profile_schema import (
    ExperienceEntry,
    ProfileData,
    profile_data_from_json,
)
from core.proposals import ProposedChange
from core.template_config import TemplateConfig, template_config_from_json

from core.resume_agent import (
    apply_approved_to_profile_pool,
    proposals_all_resolved,
)
from core.resume_parser import profile_from_legacy_fields
from core.template_extractor import _infer_order_from_text, _normalize_section_order


def _sample_profile() -> ProfileData:
    return ProfileData(
        contact=ContactInfo(name="Ada Lovelace", email="ada@example.com"),
        summary="Software engineer with Python and SQL experience.",
        skills=["Python", "SQL", "AWS", "REST APIs"],
        experience=[
            ExperienceEntry(
                id="exp-1",
                title="Backend Engineer",
                company="Acme",
                start_date="January 2022",
                end_date="Present",
                bullets=["Built APIs with Python and SQL", "Deployed services on AWS"],
            ),
            ExperienceEntry(
                id="exp-2",
                title="Junior Developer",
                company="Beta",
                start_date="March 2019",
                end_date="December 2021",
                bullets=["Maintained legacy apps"],
            ),
            ExperienceEntry(
                id="exp-3",
                title="Intern",
                company="Gamma",
                start_date="June 2018",
                end_date="August 2018",
                bullets=["Wrote scripts"],
            ),
        ],
        education=[
            ExperienceEntry(
                id="edu-1",
                title="B.S. Computer Science",
                company="State University",
                start_date="May 2018",
                end_date="May 2018",
            )
        ],
    )


def test_profile_data_roundtrip_json() -> None:
    profile = _sample_profile()
    raw = profile.model_dump_json()
    restored = profile_data_from_json(raw)
    assert restored is not None
    assert restored.contact.name == "Ada Lovelace"
    assert "Python" in restored.skills
    assert len(restored.experience) == 3


def test_profile_to_prompt_text_includes_roles() -> None:
    text = _sample_profile().to_prompt_text()
    assert "Ada Lovelace" in text
    assert "Backend Engineer" in text
    assert "Python" in text


def test_legacy_profile_parser() -> None:
    data = profile_from_legacy_fields(
        full_name="Test User",
        skills="Python, Java",
        experience="- Built things\n- Shipped features",
        education="B.S. CS",
    )
    assert data.contact.name == "Test User"
    assert "Python" in data.skills
    assert data.experience


def test_skill_in_profile() -> None:
    profile = _sample_profile()
    assert skill_in_profile("Python", profile)
    assert skill_in_profile("python", profile)
    assert not skill_in_profile("Kubernetes", profile)


def test_text_grounded_in_profile() -> None:
    profile = _sample_profile()
    assert text_grounded_in_profile("Built APIs with Python and SQL", profile)
    assert not text_grounded_in_profile("Led quantum teleportation research with lasers", profile, min_overlap=0.5)


def test_annotate_add_skill_requires_confirmation() -> None:
    profile = _sample_profile()
    proposal = ProposedChange(
        id="p1",
        type="add_skill",
        description='Add skill "Kubernetes"',
        suggested_text="Kubernetes",
        grounded_in_profile=True,
        requires_confirmation=False,
    )
    annotated = annotate_proposal_groundedness(proposal, profile)
    assert annotated.grounded_in_profile is False
    assert annotated.requires_confirmation is True


def test_match_score_prefers_overlapping_skills() -> None:
    profile = _sample_profile()
    score, matched, missing = compute_match_score(
        profile,
        "We need Python SQL AWS and Kubernetes experience",
    )
    assert score > 0
    assert "Python" in matched or any("python" in m.lower() for m in matched)
    assert any("kubernetes" in m.lower() for m in missing) or "Kubernetes" in missing


def test_template_order_inference() -> None:
    text = """Jane Doe
SKILLS
Python
EXPERIENCE
Engineer
EDUCATION
B.S.
"""
    order = _infer_order_from_text(text)
    assert order.index("Skills") < order.index("Work Experience")
    assert order.index("Work Experience") < order.index("Education")


def test_normalize_section_order_fills_missing() -> None:
    order = _normalize_section_order(["Skills", "Experience"])
    assert "Skills" in order
    assert "Work Experience" in order
    assert "Education" in order


def test_template_config_from_json() -> None:
    cfg = template_config_from_json(
        '{"primary_color":"#112233","font_family":"Helvetica","section_order":["Skills","Work Experience","Education"]}'
    )
    assert cfg.primary_color == "#112233"
    assert cfg.font_family == "Helvetica"
    assert cfg.section_order[0] == "Skills"


def test_proposals_all_resolved() -> None:
    pending = [
        ProposedChange(id="1", type="add_skill", description="x", status="pending"),
        ProposedChange(id="2", type="add_skill", description="y", status="approved"),
    ]
    assert proposals_all_resolved(pending) is False
    pending[0] = pending[0].model_copy(update={"status": "rejected"})
    assert proposals_all_resolved(pending) is True


def test_apply_approved_adds_skill_and_excludes_role() -> None:
    profile = _sample_profile()
    proposals = [
        ProposedChange(
            id="s1",
            type="add_skill",
            description="Add K8s",
            suggested_text="Kubernetes",
            status="approved",
        ),
        ProposedChange(
            id="e1",
            type="exclude_role",
            description="Exclude intern",
            suggested_text="exp-3",
            target_entry_id="exp-3",
            status="approved",
        ),
    ]
    constrained = apply_approved_to_profile_pool(profile, proposals)
    assert "Kubernetes" in constrained.skills
    assert all(e.id != "exp-3" for e in constrained.experience)
    assert any(e.id == "exp-1" for e in constrained.experience)


def test_default_template_config() -> None:
    cfg = TemplateConfig()
    assert "Professional Summary" in cfg.section_order
    assert cfg.primary_color.startswith("#")
