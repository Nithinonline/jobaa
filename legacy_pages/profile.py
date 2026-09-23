from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st
from sqlalchemy.orm import Session

from db.models import Profile
from db.session import SessionLocal


def get_or_create_profile(session: Session) -> Profile:
    profile = session.query(Profile).filter(Profile.user_id == st.session_state.user.id).first()
    if not profile:
        profile = Profile(user_id=st.session_state.user.id)
        session.add(profile)
        session.commit()
        session.refresh(profile)
    return profile


def render_profile_page() -> None:
    st.title("Profile")
    st.caption("Create and maintain the profile data that powers resume tailoring.")

    session = SessionLocal()
    try:
        profile = get_or_create_profile(session)
        with st.form("profile_form"):
            full_name = st.text_input("Full name", value=profile.full_name or "")
            email = st.text_input("Email", value=profile.email or "")
            phone = st.text_input("Phone", value=profile.phone or "")
            location = st.text_input("Location", value=profile.location or "")
            summary = st.text_area("Professional summary", value=profile.summary or "")
            skills = st.text_area("Skills", value=profile.skills or "")
            experience = st.text_area("Experience", value=profile.experience or "")
            projects = st.text_area("Projects", value=profile.projects or "")
            education = st.text_area("Education", value=profile.education or "")
            certifications = st.text_area("Certifications", value=profile.certifications or "")
            achievements = st.text_area("Achievements", value=profile.achievements or "")
            github = st.text_input("GitHub", value=profile.github or "")
            linkedin = st.text_input("LinkedIn", value=profile.linkedin or "")
            portfolio = st.text_input("Portfolio", value=profile.portfolio or "")

            submitted = st.form_submit_button("Save profile")
            if submitted:
                profile.full_name = full_name
                profile.email = email
                profile.phone = phone
                profile.location = location
                profile.summary = summary
                profile.skills = skills
                profile.experience = experience
                profile.projects = projects
                profile.education = education
                profile.certifications = certifications
                profile.achievements = achievements
                profile.github = github
                profile.linkedin = linkedin
                profile.portfolio = portfolio
                session.commit()
                st.success("Profile saved.")
    finally:
        session.close()
