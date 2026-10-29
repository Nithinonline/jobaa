"""Hybrid retriever: Chroma vector hits + alias/keyword evidence from ProfileData."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from core.config_loader import get_embeddings_config
from core.jd_parser import get_priority_keywords, job_description_to_parsed
from core.profile_diff import skill_in_profile
from core.profile_schema import ProfileData
from core.skill_aliases import expand_aliases, normalize_skill_token
from core.vectorstore import RetrievedChunk, query_chunks

if TYPE_CHECKING:
    from db.models import JobDescription


@dataclass
class EvidenceHit:
    chunk_id: str
    text: str
    chunk_type: str
    entry_id: str
    parent_id: str
    score: float
    source: str  # vector | alias | both
    query: str = ""


@dataclass
class RetrievalBundle:
    """Aggregated evidence for a JD analysis."""

    hits: list[EvidenceHit] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    evidence_prompt: str = ""
    role_scores: dict[str, float] = field(default_factory=dict)

    def top_texts(self, limit: int = 20) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for hit in sorted(self.hits, key=lambda h: h.score, reverse=True):
            key = hit.text.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(hit.text)
            if len(out) >= limit:
                break
        return out


def _jd_requirements(jd: Optional["JobDescription"], jd_text: str) -> list[str]:
    reqs: list[str] = []
    if jd is not None:
        parsed = job_description_to_parsed(jd)
        for item in parsed.required_skills + parsed.technologies + parsed.preferred_skills:
            if item.strip():
                reqs.append(item.strip())
        for resp in parsed.responsibilities[:12]:
            if resp.strip():
                reqs.append(resp.strip())
        for kw in get_priority_keywords(jd, limit=15):
            if kw.strip() and kw not in reqs:
                reqs.append(kw.strip())
    if not reqs and jd_text:
        # Split into sentences / lines as soft requirements
        for part in jd_text.replace("\r", "\n").split("\n"):
            part = part.strip(" •-\t")
            if len(part) > 20:
                reqs.append(part[:300])
            if len(reqs) >= 15:
                break
    # Dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for r in reqs:
        key = r.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out[:20]


def _alias_hits_for_requirement(
    requirement: str,
    profile: ProfileData,
) -> list[EvidenceHit]:
    """Find profile skills/bullets that alias-match the requirement."""
    hits: list[EvidenceHit] = []
    needle = normalize_skill_token(requirement)
    if not needle:
        return hits

    if skill_in_profile(requirement, profile):
        for skill in profile.all_skill_tokens():
            if expand_aliases(skill) & expand_aliases(requirement):
                hits.append(
                    EvidenceHit(
                        chunk_id=f"alias-skill-{normalize_skill_token(skill)}",
                        text=f"Skill: {skill}",
                        chunk_type="skill_group",
                        entry_id="skills",
                        parent_id="",
                        score=0.9,
                        source="alias",
                        query=requirement,
                    )
                )
                break

    # Scan bullets for alias token overlap
    req_forms = expand_aliases(requirement)
    for entry in profile.experience + profile.projects:
        for idx, bullet in enumerate(entry.bullets or []):
            lower = bullet.lower()
            if any(form and form in normalize_skill_token(lower) for form in req_forms if len(form) >= 3):
                hits.append(
                    EvidenceHit(
                        chunk_id=f"alias-{entry.id}-b{idx}",
                        text=bullet,
                        chunk_type="bullet",
                        entry_id=f"{entry.id}-b{idx}",
                        parent_id=entry.id,
                        score=0.75,
                        source="alias",
                        query=requirement,
                    )
                )
    return hits[:3]


def _merge_hits(vector: list[RetrievedChunk], alias: list[EvidenceHit], query: str) -> list[EvidenceHit]:
    by_id: dict[str, EvidenceHit] = {}
    for vh in vector:
        by_id[vh.id] = EvidenceHit(
            chunk_id=vh.id,
            text=vh.text,
            chunk_type=vh.chunk_type,
            entry_id=vh.entry_id,
            parent_id=vh.parent_id,
            score=vh.score,
            source="vector",
            query=query,
        )
    for ah in alias:
        existing = by_id.get(ah.chunk_id)
        if existing:
            existing.score = max(existing.score, ah.score) + 0.1
            existing.source = "both"
        else:
            by_id[ah.chunk_id] = ah
    return sorted(by_id.values(), key=lambda h: h.score, reverse=True)


def retrieve_evidence(
    user_id: int,
    profile: ProfileData,
    jd_text: str,
    jd: Optional["JobDescription"] = None,
    *,
    n_results: int | None = None,
) -> RetrievalBundle:
    """Hybrid retrieve supporting master-resume evidence for a JD."""
    n = n_results if n_results is not None else int(get_embeddings_config()["n_results"])
    requirements = _jd_requirements(jd, jd_text)
    all_hits: list[EvidenceHit] = []
    role_scores: dict[str, float] = {e.id: 0.0 for e in profile.experience if e.id}

    for req in requirements:
        try:
            vector_hits = query_chunks(user_id, req, n_results=n)
        except Exception:
            vector_hits = []
        alias_hits = _alias_hits_for_requirement(req, profile)
        merged = _merge_hits(vector_hits, alias_hits, req)
        all_hits.extend(merged)

        for hit in merged:
            role_id = hit.parent_id or (hit.entry_id if hit.chunk_type == "experience" else "")
            if role_id and role_id in role_scores:
                role_scores[role_id] = max(role_scores[role_id], hit.score)

    # Also score experience headers against full JD title/text
    jd_blob = (jd.title if jd is not None else "") or ""
    if jd is not None:
        parsed = job_description_to_parsed(jd)
        jd_blob = " ".join(
            [parsed.title, " ".join(parsed.required_skills[:10]), " ".join(parsed.responsibilities[:5])]
        )
    elif jd_text:
        jd_blob = jd_text[:1500]

    if jd_blob.strip():
        try:
            exp_hits = query_chunks(
                user_id,
                jd_blob,
                n_results=max(n, len(profile.experience) or 1),
                chunk_types=["experience", "bullet"],
            )
            for hit in exp_hits:
                role_id = hit.parent_id or (hit.entry_id if hit.chunk_type == "experience" else "")
                if role_id and role_id in role_scores:
                    role_scores[role_id] = max(role_scores[role_id], hit.score)
                all_hits.append(
                    EvidenceHit(
                        chunk_id=hit.id,
                        text=hit.text,
                        chunk_type=hit.chunk_type,
                        entry_id=hit.entry_id,
                        parent_id=hit.parent_id,
                        score=hit.score,
                        source="vector",
                        query="jd_blob",
                    )
                )
        except Exception:
            pass

    # Dedupe hits by chunk_id keeping best score
    dedup: dict[str, EvidenceHit] = {}
    for hit in all_hits:
        prev = dedup.get(hit.chunk_id)
        if prev is None or hit.score > prev.score:
            dedup[hit.chunk_id] = hit
    ranked = sorted(dedup.values(), key=lambda h: h.score, reverse=True)

    lines = []
    for hit in ranked[:25]:
        cite = f"[{hit.chunk_id}|{hit.chunk_type}]"
        lines.append(f"{cite} {hit.text}")

    return RetrievalBundle(
        hits=ranked,
        requirements=requirements,
        evidence_prompt="\n".join(lines) if lines else "(no retrieved evidence)",
        role_scores=role_scores,
    )


def format_evidence_for_prompt(bundle: RetrievalBundle, limit: int = 20) -> str:
    texts = bundle.top_texts(limit=limit)
    if not texts:
        return bundle.evidence_prompt
    return "\n".join(f"- {t}" for t in texts)
