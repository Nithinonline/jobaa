"""Stateful resume tailoring agent with confirmation proposals."""

from __future__ import annotations

import json
import re
import uuid
from typing import TYPE_CHECKING, Any, Optional

from core.jd_parser import format_jd_for_prompt, get_priority_keywords
from core.llm_client import llm_client
from core.matcher import compute_match_score
from core.profile_diff import annotate_proposal_groundedness, skill_in_profile
from core.profile_schema import ProfileData
from core.template_config import TemplateConfig
from core.proposals import ProposedChange
from core.resume_generator import generate_resume

if TYPE_CHECKING:
    from db.models import JobDescription


def _extract_json_array(text: str) -> list[Any]:
    text = (text or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and "proposals" in parsed:
            return list(parsed["proposals"])
    except json.JSONDecodeError:
        pass
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    return []


def analyze_tailoring_needs(
    profile: ProfileData,
    jd_text: str,
    jd: Optional["JobDescription"] = None,
) -> list[ProposedChange]:
    """Compare master profile to JD and produce confirmation proposals."""
    priority = get_priority_keywords(jd) if jd is not None else []
    jd_prompt = format_jd_for_prompt(jd) if jd is not None else jd_text
    profile_text = profile.to_prompt_text()

    proposals: list[ProposedChange] = []

    # Deterministic skill-gap proposals
    for skill in priority:
        if not skill_in_profile(skill, profile):
            proposals.append(
                ProposedChange(
                    id=f"skill-{uuid.uuid4().hex[:8]}",
                    type="add_skill",
                    description=f'Add skill "{skill}"',
                    suggested_text=skill,
                    jd_evidence=f'Required/priority term in JD: "{skill}"',
                    grounded_in_profile=False,
                    requires_confirmation=True,
                    status="pending",
                )
            )

    # Role selection for one-page fit (keep top roles by default)
    if len(profile.experience) > 2:
        for entry in profile.experience[2:]:
            proposals.append(
                ProposedChange(
                    id=f"exclude-{entry.id or uuid.uuid4().hex[:8]}",
                    type="exclude_role",
                    description=f'Exclude older role to fit one page: {entry.title} at {entry.company}',
                    suggested_text=entry.id,
                    jd_evidence="One-page budget: prefer most recent / most relevant roles",
                    grounded_in_profile=True,
                    requires_confirmation=True,
                    status="pending",
                    target_entry_id=entry.id,
                )
            )

    prompt = f"""You are a resume tailoring agent. Compare the master profile to the job description.
Propose ONLY helpful changes. Do NOT invent jobs the candidate never held.
Return ONLY a JSON array of proposal objects with fields:
- type: one of add_bullet, reword_bullet, reword_summary, include_role
- description: short human-readable summary
- suggested_text: the exact text to use if approved
- jd_evidence: which JD requirement this addresses
- target_entry_id: experience/project id from profile when relevant (or empty)
- grounded_in_profile: true if fully supported by master profile content

Master profile:
{profile_text[:12000]}

Job description:
{jd_prompt[:6000]}

Priority JD terms: {', '.join(priority[:30])}
"""
    try:
        response = llm_client.generate(prompt)
        raw_items = _extract_json_array(response)
    except Exception:
        raw_items = []

    allowed_types = {"add_bullet", "reword_bullet", "reword_summary", "include_role", "add_certification"}
    for item in raw_items[:12]:
        if not isinstance(item, dict):
            continue
        ptype = str(item.get("type") or "").strip()
        if ptype not in allowed_types:
            continue
        # Skip add_skill from LLM — already covered deterministically
        proposal = ProposedChange(
            id=f"llm-{uuid.uuid4().hex[:8]}",
            type=ptype,  # type: ignore[arg-type]
            description=str(item.get("description") or ptype),
            suggested_text=str(item.get("suggested_text") or ""),
            jd_evidence=str(item.get("jd_evidence") or ""),
            grounded_in_profile=bool(item.get("grounded_in_profile", True)),
            requires_confirmation=True,
            status="pending",
            target_entry_id=str(item.get("target_entry_id") or "") or None,
        )
        proposals.append(annotate_proposal_groundedness(proposal, profile))

    # Cap add_skill proposals
    skill_props = [p for p in proposals if p.type == "add_skill"]
    other = [p for p in proposals if p.type != "add_skill"]
    return skill_props[:8] + other[:10]


def proposals_all_resolved(proposals: list[ProposedChange]) -> bool:
    return all(p.status in ("approved", "rejected", "edited") for p in proposals)


def apply_approved_to_profile_pool(
    profile: ProfileData,
    proposals: list[ProposedChange],
) -> ProfileData:
    """Build a constrained profile pool from approved proposals."""
    data = profile.model_dump()
    contact = profile.contact

    approved = [p for p in proposals if p.status in ("approved", "edited")]
    rejected_exclude_ids = {
        p.target_entry_id
        for p in proposals
        if p.type == "exclude_role" and p.status in ("approved", "edited") and p.target_entry_id
    }
    # If user rejects an exclude proposal, keep the role
    rejected_exclude_ids -= {
        p.target_entry_id
        for p in proposals
        if p.type == "exclude_role" and p.status == "rejected" and p.target_entry_id
    }

    experience = [e for e in profile.experience if e.id not in rejected_exclude_ids]

    for proposal in approved:
        if proposal.type == "add_skill" and proposal.suggested_text:
            skills = list(data.get("skills") or [])
            if proposal.suggested_text not in skills:
                skills.append(proposal.suggested_text)
            data["skills"] = skills
        elif proposal.type == "reword_summary" and proposal.suggested_text:
            data["summary"] = proposal.suggested_text
        elif proposal.type == "add_certification" and proposal.suggested_text:
            certs = list(data.get("certifications") or [])
            if proposal.suggested_text not in certs:
                certs.append(proposal.suggested_text)
            data["certifications"] = certs
        elif proposal.type in ("add_bullet", "reword_bullet") and proposal.suggested_text:
            target_id = proposal.target_entry_id
            for idx, entry in enumerate(experience):
                if target_id and entry.id == target_id:
                    bullets = list(entry.bullets)
                    if proposal.type == "reword_bullet" and bullets:
                        bullets[0] = proposal.suggested_text
                    else:
                        bullets.append(proposal.suggested_text)
                    experience[idx] = entry.model_copy(update={"bullets": bullets})
                    break
            else:
                if experience:
                    bullets = list(experience[0].bullets) + [proposal.suggested_text]
                    experience[0] = experience[0].model_copy(update={"bullets": bullets})

    data["experience"] = [e.model_dump() for e in experience]
    data["contact"] = {
        "name": contact.name,
        "email": contact.email,
        "phone": contact.phone,
        "location": contact.location,
        "linkedin": contact.linkedin,
        "github": contact.github,
        "portfolio": contact.portfolio,
    }
    return ProfileData.model_validate(data)


def persist_approved_skills_to_master(
    profile: ProfileData,
    proposals: list[ProposedChange],
) -> ProfileData:
    """Merge skills the user marked persist_to_master into the master profile."""
    skills = list(profile.skills)
    for proposal in proposals:
        if (
            proposal.type == "add_skill"
            and proposal.status in ("approved", "edited")
            and proposal.persist_to_master
            and proposal.suggested_text
            and proposal.suggested_text not in skills
        ):
            skills.append(proposal.suggested_text)
    return profile.model_copy(update={"skills": skills})


def generate_tailored_resume(
    profile: ProfileData,
    jd_text: str,
    proposals: list[ProposedChange],
    *,
    jd: Optional["JobDescription"] = None,
    template_config: Optional[TemplateConfig] = None,
    max_iterations: Optional[int] = None,
) -> dict:
    """Generate resume only from approved proposals + master profile pool."""
    if not proposals_all_resolved(proposals):
        pending = [p.id for p in proposals if p.status == "pending"]
        raise ValueError(f"Resolve all proposals before generating. Pending: {pending}")

    constrained = apply_approved_to_profile_pool(profile, proposals)
    allowed_skills = list(constrained.skills)
    selected_experience_ids = [e.id for e in constrained.experience if e.id]

    section_order = None
    if template_config is not None:
        section_order = template_config.section_order

    result = generate_resume(
        constrained.to_prompt_text(),
        jd_text,
        max_iterations=max_iterations,
        jd=jd,
        allowed_skills=allowed_skills,
        selected_experience_ids=selected_experience_ids,
        section_order=section_order,
    )
    match_score, _matched, _missing = compute_match_score(constrained, jd_text, jd=jd)
    result["match_score"] = match_score
    result["constrained_profile"] = constrained
    return result
