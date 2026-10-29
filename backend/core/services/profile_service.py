"""Profile load/save and Chroma reindex."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from core.ats_constants import ContactInfo
from core.chunker import reindex_profile
from core.layout_schema import MasterLayoutProfile, master_layout_profile_from_json
from core.profile_schema import ProfileData, profile_data_from_json
from core.resume_parser import profile_from_legacy_fields
from core.template_config import TemplateConfig, template_config_from_json
from db.models import Profile


def get_or_create_profile(session: Session, user_id: int) -> Profile:
    profile = session.query(Profile).filter(Profile.user_id == user_id).first()
    if not profile:
        profile = Profile(user_id=user_id, profile_source="manual")
        session.add(profile)
        session.commit()
        session.refresh(profile)
    return profile


def load_profile_data(profile: Profile) -> ProfileData | None:
    data = profile_data_from_json(profile.structured_profile_json)
    if data:
        return data
    if any([profile.full_name, profile.skills, profile.experience, profile.summary]):
        return profile_from_legacy_fields(
            full_name=profile.full_name or "",
            email=profile.email or "",
            phone=profile.phone or "",
            location=profile.location or "",
            linkedin=profile.linkedin or "",
            github=profile.github or "",
            portfolio=profile.portfolio or "",
            summary=profile.summary or "",
            skills=profile.skills or "",
            experience=profile.experience or "",
            projects=profile.projects or "",
            education=profile.education or "",
            certifications=profile.certifications or "",
            achievements=profile.achievements or "",
        )
    return None


def apply_profile_data_to_model(profile: Profile, data: ProfileData, *, source: str | None = None) -> None:
    flat = data.to_flat_fields()
    profile.full_name = flat["full_name"]
    profile.email = flat["email"]
    profile.phone = flat["phone"]
    profile.location = flat["location"]
    profile.linkedin = flat["linkedin"]
    profile.github = flat["github"]
    profile.portfolio = flat["portfolio"]
    profile.summary = flat["summary"]
    profile.skills = flat["skills"]
    profile.experience = flat["experience"]
    profile.projects = flat["projects"]
    profile.education = flat["education"]
    profile.certifications = flat["certifications"]
    profile.achievements = flat["achievements"]
    profile.structured_profile_json = data.model_dump_json()
    if source:
        profile.profile_source = source


def get_layout_profile(profile: Profile) -> MasterLayoutProfile:
    return master_layout_profile_from_json(profile.layout_profile_json)


def get_template_config(profile: Profile) -> TemplateConfig:
    if profile.layout_profile_json:
        return get_layout_profile(profile).to_template_config()
    return template_config_from_json(profile.template_config_json)


def build_profile_text(profile: Profile) -> str:
    data = load_profile_data(profile)
    if data:
        return data.to_prompt_text()
    contact_parts: list[str] = []
    if profile.full_name:
        contact_parts.append(f"Name: {profile.full_name}")
    if profile.email:
        contact_parts.append(f"Email: {profile.email}")
    if profile.phone:
        contact_parts.append(f"Phone: {profile.phone}")
    if profile.location:
        contact_parts.append(f"Location: {profile.location}")
    sections: list[str] = []
    if contact_parts:
        sections.append("Contact:\n" + "\n".join(contact_parts))
    for label, value in [
        ("Summary", profile.summary),
        ("Skills", profile.skills),
        ("Experience", profile.experience),
        ("Projects", profile.projects),
        ("Education", profile.education),
        ("Certifications", profile.certifications),
        ("Achievements", profile.achievements),
    ]:
        if value:
            sections.append(f"{label}:\n{value}")
    return "\n\n".join(sections)


def save_master_profile(
    session: Session,
    profile: Profile,
    data: ProfileData,
    *,
    source: str = "upload",
    raw_text: str | None = None,
    filename: str | None = None,
    raw_bytes: bytes | None = None,
    mime_type: str | None = None,
    layout_profile: MasterLayoutProfile | None = None,
    template_config: TemplateConfig | None = None,
    reindex: bool = True,
) -> int:
    """
    Persist structured profile to SQLite and optionally reindex Chroma.
    Returns number of Chroma chunks indexed (0 if reindex skipped/failed).
    """
    apply_profile_data_to_model(profile, data, source=source)
    if raw_text is not None:
        profile.master_resume_raw_text = raw_text
    if filename is not None:
        profile.master_resume_filename = filename
    if raw_bytes is not None:
        profile.master_resume_bytes = raw_bytes
    if mime_type is not None:
        profile.master_resume_mime_type = mime_type
    if layout_profile is not None:
        profile.layout_profile_json = layout_profile.model_dump_json()
        profile.master_page_count = layout_profile.page_count
        profile.template_config_json = layout_profile.to_template_config().model_dump_json()
    elif template_config is not None:
        profile.template_config_json = template_config.model_dump_json()
    elif not profile.template_config_json:
        profile.template_config_json = TemplateConfig().model_dump_json()

    session.commit()

    chunk_count = 0
    if reindex:
        try:
            chunk_count = reindex_profile(profile.user_id, data)
        except Exception:
            chunk_count = 0
    return chunk_count
