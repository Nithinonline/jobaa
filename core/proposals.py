"""Agent proposal models (leaf module — no project circular deps)."""

from __future__ import annotations

import json
from typing import Literal, Optional

from pydantic import BaseModel

ProposalType = Literal[
    "add_skill",
    "add_bullet",
    "include_role",
    "exclude_role",
    "reword_summary",
    "add_certification",
    "reword_bullet",
]

ProposalStatus = Literal["pending", "approved", "rejected", "edited"]


class ProposedChange(BaseModel):
    """A single agent proposal the user must approve, reject, or edit."""

    id: str
    type: ProposalType
    description: str
    suggested_text: str = ""
    jd_evidence: str = ""
    grounded_in_profile: bool = True
    requires_confirmation: bool = False
    status: ProposalStatus = "pending"
    target_entry_id: Optional[str] = None
    persist_to_master: bool = False


def proposals_from_json(raw: str | None) -> list[ProposedChange]:
    if not raw or not raw.strip():
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [ProposedChange.model_validate(item) for item in data]
    except (json.JSONDecodeError, ValueError):
        return []
    return []
