"""Legacy resume generation page — delegates to ATS-safe core exporters."""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from core.cache import get_or_create_job_description
from core.config_loader import get_thresholds
from core.file_parser import parse_uploaded_file
from core.jd_parser import get_priority_keywords
from core.pdf_exporter import generate_docx_bytes, generate_pdf_bytes
from core.resume_validator import validate_exported_resume
from core.resume_generator import generate_resume
from db.models import Profile, ResumeVersion
from db.session import SessionLocal


def save_resume_version(
    user_id: int,
    job_id: int | None,
    markdown_content: str,
    ats_score: float,
    summary: str,
    missing_keywords: str,
) -> None:
    session = SessionLocal()
    try:
        version = ResumeVersion(
            user_id=user_id,
            job_description_id=job_id,
            version_name="v1",
            markdown_content=markdown_content,
            ats_score=float(ats_score),
            improvement_summary=summary,
            missing_keywords=missing_keywords,
        )
        session.add(version)
        session.commit()
    finally:
        session.close()


def _build_profile_text(profile: Profile) -> str:
    sections: list[str] = []
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


def render_resume_generation_page() -> None:
    st.title("Resume Generation")
    st.caption("Generate an ATS-friendly tailored resume using the core export pipeline.")

    session = SessionLocal()
    try:
        profile = session.query(Profile).filter(Profile.user_id == st.session_state.user.id).first()
        if not profile:
            st.info("Complete your profile first before generating a tailored resume.")
            return

        uploaded_file = st.file_uploader("Job description file", type=["pdf", "docx", "txt"], key="resume_jd_upload")
        pasted_text = st.text_area("Or paste job description text", key="resume_jd_text")
        title = st.text_input("Optional job title", key="resume_jd_title")

        if st.button("Generate Tailored Resume"):
            if uploaded_file is None and not pasted_text.strip():
                st.error("Please provide a file or pasted text.")
                return

            text = pasted_text.strip()
            if uploaded_file is not None:
                text = parse_uploaded_file(uploaded_file)

            jd = get_or_create_job_description(
                session=session,
                user_id=st.session_state.user.id,
                raw_text=text,
                title=title or "Untitled role",
            )
            profile_text = _build_profile_text(profile)
            thresholds = get_thresholds()
            result = generate_resume(
                profile_text,
                text,
                max_iterations=int(thresholds["max_iterations"]),
                jd=jd,
            )
            markdown_content = result["markdown_content"]
            ats_score = result["ats_score"]
            summary = result["improvements"]
            missing_keywords = result["missing_keywords"]
            priority_keywords = get_priority_keywords(jd)

            save_resume_version(
                st.session_state.user.id,
                jd.id,
                markdown_content,
                ats_score,
                summary,
                ", ".join(missing_keywords),
            )

            st.success("Resume generated and saved to history.")
            st.metric("ATS score", f"{ats_score:.1f}%")
            if missing_keywords:
                st.caption(f"Missing keywords: {', '.join(missing_keywords)}")

            pdf_bytes = generate_pdf_bytes(
                markdown_content,
                profile,
                priority_keywords,
                job_title=jd.title or title or "Job",
                profile_text=profile_text,
                rewrite_for_one_page=True,
            )
            if pdf_bytes is not None:
                _, pdf_issues = validate_exported_resume(pdf_bytes, "pdf", priority_keywords)
                st.download_button("Download PDF", pdf_bytes, file_name="resume.pdf")
                if pdf_issues:
                    st.warning("PDF ATS warnings: " + "; ".join(pdf_issues))
            else:
                st.warning("PDF export unavailable. Install reportlab: pip install reportlab")

            docx_bytes = generate_docx_bytes(markdown_content, profile, priority_keywords)
            _, docx_issues = validate_exported_resume(docx_bytes, "docx", priority_keywords)
            st.download_button("Download DOCX", docx_bytes, file_name="resume.docx")
            if docx_issues:
                st.warning("DOCX ATS warnings: " + "; ".join(docx_issues))

            st.download_button("Download Markdown", markdown_content, file_name="resume.md")
            st.markdown(markdown_content)
    finally:
        session.close()
