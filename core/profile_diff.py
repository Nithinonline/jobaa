"""Profile lookup helpers used by hybrid evidence retrieval."""

from __future__ import annotations

import re
from core.profile_schema import ProfileData
from core.skill_aliases import expand_aliases, normalize_skill_token, tokens_match


def _normalize_token(text: str) -> str:
    return normalize_skill_token(text)


def skill_in_profile(skill: str, profile: ProfileData) -> bool:
    needle = _normalize_token(skill)
    if not needle:
        return True
    needle_forms = expand_aliases(needle)
    for known in profile.all_skill_tokens():
        known_n = _normalize_token(known)
        if tokens_match(needle, known_n) or needle_forms & expand_aliases(known_n):
            return True
        if len(needle) >= 3:
            parts = re.split(r"[^a-z0-9+#]+", known_n)
            if needle in parts or any(tokens_match(needle, p) for p in parts if p):
                return True
    return False
