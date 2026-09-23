"""Skill / technology alias table and normalization helpers."""

from __future__ import annotations

import re


def normalize_skill_token(text: str) -> str:
    """Normalize a skill/tech token for comparison."""
    return re.sub(r"[^a-z0-9+#.\-/]", "", (text or "").lower()).strip()


# Canonical form -> accepted aliases.
_ALIAS_GROUPS: list[tuple[str, list[str]]] = [
    ("javascript", ["js", "java script"]),
    ("typescript", ["ts"]),
    ("kubernetes", ["k8s"]),
    ("postgresql", ["postgres", "psql"]),
    ("node.js", ["node", "nodejs"]),
    ("amazon web services", ["aws"]),
    ("google cloud", ["gcp", "google cloud platform"]),
    ("machine learning", ["ml"]),
    ("ci/cd", ["cicd", "ci-cd", "continuous integration"]),
    ("c#", ["csharp", "c sharp"]),
    ("c++", ["cpp", "cplusplus"]),
    (".net", ["dotnet", "dot net"]),
    ("react", ["reactjs", "react.js"]),
    ("vue", ["vuejs", "vue.js"]),
    ("natural language processing", ["nlp"]),
    ("rest", ["restful", "rest api", "rest apis"]),
]

# Bidirectional map: any form -> frozenset of all equivalent forms.
SKILL_ALIASES: dict[str, frozenset[str]] = {}

for _canonical, _aliases in _ALIAS_GROUPS:
    _group = frozenset(
        {normalize_skill_token(_canonical), *(normalize_skill_token(a) for a in _aliases)}
    )
    for _form in _group:
        _existing = SKILL_ALIASES.get(_form)
        if _existing:
            SKILL_ALIASES[_form] = frozenset(_existing | _group)
        else:
            SKILL_ALIASES[_form] = _group


def expand_aliases(term: str) -> frozenset[str]:
    """Return the term plus all known aliases (normalized)."""
    key = normalize_skill_token(term)
    if not key:
        return frozenset()
    aliases = SKILL_ALIASES.get(key)
    if aliases:
        return aliases
    return frozenset({key})


def tokens_match(a: str, b: str) -> bool:
    """True if two skill tokens are equal or alias-equivalent."""
    na = normalize_skill_token(a)
    nb = normalize_skill_token(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    return bool(expand_aliases(na) & expand_aliases(nb))
