"""Groundedness checks: flag content not present in the master profile."""

from __future__ import annotations

import re

from core.profile_schema import ProfileData
from core.proposals import ProposedChange
from core.skill_aliases import expand_aliases, normalize_skill_token, tokens_match


def _normalize_token(text: str) -> str:
    return normalize_skill_token(text)


def _tokenize(text: str) -> set[str]:
    parts = re.split(r"[\s,/|;]+", text or "")
    out: set[str] = set()
    for p in parts:
        n = _normalize_token(p)
        if n and len(n) > 1:
            out |= expand_aliases(n)
    return out


def profile_corpus(profile: ProfileData) -> set[str]:
    """All normalized tokens from the master profile (includes aliases)."""
    tokens = set()
    for skill in profile.all_skill_tokens():
        tokens |= expand_aliases(skill)
    tokens |= _tokenize(profile.summary)
    for entry in profile.experience + profile.projects + profile.education:
        tokens |= _tokenize(entry.title)
        tokens |= _tokenize(entry.company)
        tokens |= _tokenize(entry.location or "")
        for bullet in entry.bullets:
            tokens |= _tokenize(bullet)
    for item in profile.certifications + profile.achievements:
        tokens |= _tokenize(item)
    return tokens


def skill_in_profile(skill: str, profile: ProfileData) -> bool:
    needle = _normalize_token(skill)
    if not needle:
        return True
    needle_forms = expand_aliases(needle)
    for known in profile.all_skill_tokens():
        known_n = _normalize_token(known)
        if tokens_match(needle, known_n) or needle_forms & expand_aliases(known_n):
            return True
        # Whole-token containment (kubernetes in amazon-eks-kubernetes), not java⊂javascript
        if len(needle) >= 3:
            parts = re.split(r"[^a-z0-9+#]+", known_n)
            if needle in parts or any(tokens_match(needle, p) for p in parts if p):
                return True
    corpus = profile_corpus(profile)
    return bool(needle_forms & corpus)


def text_grounded_in_profile(text: str, profile: ProfileData, *, min_overlap: float = 0.35) -> bool:
    """Return True if most content words appear in the master profile corpus."""
    text_tokens = _tokenize(text)
    if not text_tokens:
        return True
    corpus = profile_corpus(profile)
    if not corpus:
        return False
    overlap = len(text_tokens & corpus) / max(len(text_tokens), 1)
    return overlap >= min_overlap


def annotate_proposal_groundedness(proposal: ProposedChange, profile: ProfileData) -> ProposedChange:
    """Mark whether a proposal is grounded; force confirmation when not."""
    data = proposal.model_dump()
    if proposal.type == "add_skill":
        grounded = skill_in_profile(proposal.suggested_text or proposal.description, profile)
        data["grounded_in_profile"] = grounded
        data["requires_confirmation"] = not grounded
    elif proposal.type in ("add_bullet", "reword_bullet", "reword_summary", "add_certification"):
        grounded = text_grounded_in_profile(proposal.suggested_text, profile)
        data["grounded_in_profile"] = grounded
        data["requires_confirmation"] = not grounded or proposal.type in ("add_certification", "reword_summary")
    elif proposal.type in ("include_role", "exclude_role"):
        data["grounded_in_profile"] = True
        data["requires_confirmation"] = True
    else:
        data["requires_confirmation"] = True
    return ProposedChange.model_validate(data)


def find_ungrounded_skills_in_text(text: str, profile: ProfileData, candidate_skills: list[str]) -> list[str]:
    """Return candidate skills that appear in text but not in the master profile."""
    lower = (text or "").lower()
    missing: list[str] = []
    for skill in candidate_skills:
        if skill.lower() in lower and not skill_in_profile(skill, profile):
            missing.append(skill)
    return missing
