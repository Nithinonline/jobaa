from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is importable when Streamlit runs pages or scripts from subfolders.
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st
from sqlalchemy.orm import Session

from auth.auth_config import authenticate_user, ensure_user_exists, logout
from core.cache import get_or_create_job_description
from core.config_loader import get_thresholds
from core.file_parser import parse_uploaded_file
from core.jd_parser import get_priority_keywords
from core.pdf_exporter import (
    build_resume_filename,
    generate_docx_bytes,
    generate_pdf_bytes,
)
from core.resume_validator import validate_exported_resume
from core.resume_generator import generate_resume
from db.models import Profile, ResumeVersion
from db.session import SessionLocal, init_db

st.set_page_config(page_title="Joba", page_icon="💼", layout="wide")

init_db()

if "user" not in st.session_state:
    st.session_state.user = None


def show_auth_screen() -> None:
    st.title("Joba")
    st.caption("AI-powered resume tailoring for your next opportunity")

    auth_tab = st.tabs(["Login", "Sign up"])
    with auth_tab[0]:
        username = st.text_input("Username", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")
        if st.button("Log in"):
            user = authenticate_user(username, password)
            if user:
                st.session_state.user = user
                st.rerun()
            else:
                st.error("Invalid username or password.")

    with auth_tab[1]:
        username = st.text_input("Choose a username", key="signup_username")
        email = st.text_input("Email", key="signup_email")
        password = st.text_input("Password", type="password", key="signup_password")
        if st.button("Create account"):
            try:
                ensure_user_exists(username, email, password)
                st.success("Account created. You can now log in.")
            except ValueError as exc:
                st.error(str(exc))


def get_or_create_profile(session: Session) -> Profile:
    """Fetch or create a profile for the current user."""
    profile = session.query(Profile).filter(Profile.user_id == st.session_state.user.id).first()
    if not profile:
        profile = Profile(user_id=st.session_state.user.id)
        session.add(profile)
        session.commit()
        session.refresh(profile)
    return profile


def build_profile_text(profile: Profile) -> str:
    """Combine all profile fields into a single text block for LLM context."""
    contact_parts: list[str] = []
    if profile.full_name:
        contact_parts.append(f"Name: {profile.full_name}")
    if profile.email:
        contact_parts.append(f"Email: {profile.email}")
    if profile.phone:
        contact_parts.append(f"Phone: {profile.phone}")
    if profile.location:
        contact_parts.append(f"Location: {profile.location}")
    if profile.linkedin:
        contact_parts.append(f"LinkedIn: {profile.linkedin}")
    if profile.github:
        contact_parts.append(f"GitHub: {profile.github}")
    if profile.portfolio:
        contact_parts.append(f"Portfolio: {profile.portfolio}")

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


def save_resume_to_db(
    user_id: int,
    job_id: int | None,
    markdown_content: str,
    ats_score: float,
    improvements: str,
    missing_keywords: list[str],
) -> None:
    """Save generated resume to database."""
    session = SessionLocal()
    try:
        version = ResumeVersion(
            user_id=user_id,
            job_description_id=job_id,
            markdown_content=markdown_content,
            ats_score=float(ats_score),
            improvement_summary=improvements,
            missing_keywords=", ".join(missing_keywords),
        )
        session.add(version)
        session.commit()
    finally:
        session.close()


def _resolve_profile_for_export(session: Session, profile: Profile) -> Profile:
    """Return the profile tied to the generated resume, if available."""
    profile_id = st.session_state.get("generated_profile_id")
    if profile_id:
        stored_profile = session.query(Profile).filter(Profile.id == profile_id).first()
        if stored_profile:
            return stored_profile
    return profile


def _get_export_keywords() -> list[str]:
    return st.session_state.get("generated_priority_keywords", [])


def _export_pdf_with_validation(
    markdown: str,
    profile: Profile,
    keywords: list[str] | None = None,
    job_title: str | None = None,
    profile_text: str | None = None,
) -> tuple[bytes | None, list[str]]:
    """Generate PDF bytes and return validation issues."""
    try:
        pdf_bytes = generate_pdf_bytes(
            markdown,
            profile,
            keywords,
            job_title=job_title,
            profile_text=profile_text,
            rewrite_for_one_page=True,
        )
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"PDF generation failed: {exc}") from exc

    if pdf_bytes is None:
        return None, []

    _, issues = validate_exported_resume(pdf_bytes, "pdf", keywords)
    return pdf_bytes, issues


def _export_docx_with_validation(
    markdown: str,
    profile: Profile,
    keywords: list[str] | None = None,
) -> tuple[bytes, list[str]]:
    """Generate DOCX bytes and return validation issues."""
    docx_bytes = generate_docx_bytes(markdown, profile, keywords)
    _, issues = validate_exported_resume(docx_bytes, "docx", keywords)
    return docx_bytes, issues


def _ensure_pdf_bytes(session: Session, profile: Profile) -> tuple[bytes | None, str, str | None]:
    """Return PDF bytes, filename, and optional error message."""
    pdf_bytes = st.session_state.get("generated_pdf_bytes")
    pdf_filename = st.session_state.get("generated_pdf_filename", "resume.pdf")
    if pdf_bytes:
        return pdf_bytes, pdf_filename, None

    markdown = st.session_state.get("generated_resume")
    if not markdown:
        return None, pdf_filename, "No resume content available."

    export_profile = _resolve_profile_for_export(session, profile)
    try:
        pdf_bytes, issues = _export_pdf_with_validation(
            markdown,
            export_profile,
            _get_export_keywords(),
            st.session_state.get("generated_job_title"),
            build_profile_text(export_profile),
        )
    except RuntimeError as exc:
        return None, pdf_filename, str(exc)
    except Exception as exc:
        return None, pdf_filename, f"PDF generation failed: {exc}"

    if pdf_bytes is None:
        return None, pdf_filename, "reportlab is not installed. Run: pip install reportlab"

    st.session_state.export_validation_issues = issues

    job_title = st.session_state.get("generated_job_title", "Job")
    pdf_filename = build_resume_filename(export_profile, job_title)
    st.session_state.generated_pdf_bytes = pdf_bytes
    st.session_state.generated_pdf_filename = pdf_filename
    return pdf_bytes, pdf_filename, None


def _clear_generated_resume_state() -> None:
    for key in (
        "generated_resume",
        "generated_ats_score",
        "generated_improvements",
        "generated_missing_keywords",
        "generated_pdf_bytes",
        "generated_pdf_filename",
        "generated_profile_id",
        "generated_job_title",
        "generated_priority_keywords",
        "export_validation_issues",
    ):
        if key in st.session_state:
            del st.session_state[key]


def _render_pdf_preview(pdf_bytes: bytes) -> None:
    """Show inline PDF preview when streamlit-pdf is available."""
    try:
        st.pdf(pdf_bytes)
    except Exception:
        st.caption("PDF preview unavailable. Use the download button below to open your resume.")


def show_main_app() -> None:
    """Render the single-page resume tool."""
    st.title("Joba Resume Tailoring")
    st.caption("AI-powered resume optimization for your target job")

    st.sidebar.title("Account")
    st.sidebar.write(f"**{st.session_state.user.username}**")
    st.sidebar.button("Log out", on_click=logout, use_container_width=True)

    session = SessionLocal()
    try:
        st.header("1. Your Profile")
        st.write("Create and save your professional profile.")

        profile = get_or_create_profile(session)

        with st.form("profile_form"):
            col1, col2 = st.columns(2)
            with col1:
                full_name = st.text_input("Full Name", value=profile.full_name or "", key="full_name")
                email = st.text_input("Email", value=profile.email or "", key="email")
                phone = st.text_input("Phone", value=profile.phone or "", key="phone")

            with col2:
                location = st.text_input("Location", value=profile.location or "", key="location")
                linkedin = st.text_input("LinkedIn (optional)", value=profile.linkedin or "", key="linkedin")
                github = st.text_input("GitHub (optional)", value=profile.github or "", key="github")

            summary = st.text_area("Professional Summary", value=profile.summary or "", height=80, key="summary")
            skills = st.text_area("Skills (comma or newline separated)", value=profile.skills or "", height=80, key="skills")
            experience = st.text_area("Experience", value=profile.experience or "", height=100, key="experience")
            projects = st.text_area("Projects (optional)", value=profile.projects or "", height=80, key="projects")
            education = st.text_area("Education", value=profile.education or "", height=80, key="education")
            certifications = st.text_area("Certifications (optional)", value=profile.certifications or "", height=60, key="certifications")
            achievements = st.text_area("Achievements (optional)", value=profile.achievements or "", height=60, key="achievements")

            submitted = st.form_submit_button("Save Profile", use_container_width=True)
            if submitted:
                profile.full_name = full_name
                profile.email = email
                profile.phone = phone
                profile.location = location
                profile.linkedin = linkedin
                profile.github = github
                profile.summary = summary
                profile.skills = skills
                profile.experience = experience
                profile.projects = projects
                profile.education = education
                profile.certifications = certifications
                profile.achievements = achievements
                session.commit()
                st.success("✅ Profile saved successfully!")

        st.divider()

        st.header("2. Target Job")
        st.write("Paste or upload the job description you're applying for.")

        jd_input_method = st.radio("JD Input Method", ["Paste Text", "Upload File"], horizontal=True, key="jd_input_method")

        jd_text = ""
        jd_title = st.text_input("Job Title (optional)", key="jd_title")

        if jd_input_method == "Paste Text":
            jd_text = st.text_area("Job Description", height=150, key="jd_paste")
        else:
            uploaded_file = st.file_uploader("Upload Job Description (PDF, DOCX, or TXT)", type=["pdf", "docx", "txt"], key="jd_upload")
            if uploaded_file is not None:
                try:
                    jd_text = parse_uploaded_file(uploaded_file)
                    st.success("✅ File parsed successfully")
                except Exception as e:
                    st.error(f"Failed to parse file: {e}")

        st.divider()

        st.header("3. Generate Resume")

        if st.button("🚀 Generate Tailored Resume", use_container_width=True, type="primary"):
            profile_text = build_profile_text(profile)
            if not profile_text.strip():
                st.error("❌ Please fill in your profile first.")
            elif not jd_text.strip():
                st.error("❌ Please provide a job description.")
            else:
                with st.spinner("🔄 Parsing job description and generating resume... (this may take 30-60 seconds)"):
                    try:
                        jd_record = get_or_create_job_description(
                            session,
                            st.session_state.user.id,
                            jd_text,
                            jd_title or "Untitled role",
                        )

                        thresholds = get_thresholds()
                        result = generate_resume(
                            profile_text,
                            jd_text,
                            max_iterations=int(thresholds["max_iterations"]),
                            jd=jd_record,
                        )
                        markdown_content = result["markdown_content"]
                        ats_score = result["ats_score"]
                        improvements = result["improvements"]
                        missing_keywords = result["missing_keywords"]

                        priority_keywords = get_priority_keywords(jd_record)
                        export_issues: list[str] = []
                        generated_job_title = jd_record.title or jd_title or "Job"
                        try:
                            pdf_bytes, export_issues = _export_pdf_with_validation(
                                markdown_content,
                                profile,
                                priority_keywords,
                                generated_job_title,
                                profile_text,
                            )
                        except RuntimeError as exc:
                            st.warning(f"Resume saved, but PDF export failed: {exc}")
                            pdf_bytes = None
                        except Exception as exc:
                            st.warning(f"Resume saved, but PDF export failed: {exc}")
                            pdf_bytes = None

                        if pdf_bytes is None:
                            try:
                                import reportlab  # noqa: F401
                            except ImportError:
                                st.warning(
                                    "PDF export needs reportlab. Install it with: "
                                    "`.venv\\Scripts\\pip install reportlab`"
                                )

                        pdf_filename = build_resume_filename(profile, generated_job_title)

                        save_resume_to_db(
                            st.session_state.user.id,
                            jd_record.id,
                            markdown_content,
                            ats_score,
                            improvements,
                            missing_keywords,
                        )

                        st.session_state.generated_resume = markdown_content
                        st.session_state.generated_ats_score = ats_score
                        st.session_state.generated_improvements = improvements
                        st.session_state.generated_missing_keywords = missing_keywords
                        st.session_state.generated_pdf_bytes = pdf_bytes
                        st.session_state.generated_pdf_filename = pdf_filename
                        st.session_state.generated_profile_id = profile.id
                        st.session_state.generated_job_title = generated_job_title
                        st.session_state.generated_priority_keywords = priority_keywords
                        st.session_state.export_validation_issues = export_issues

                        st.success("✅ Resume generated and saved!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error generating resume: {e}")

        st.divider()

        if "generated_resume" in st.session_state:
            st.header("4. Your Generated Resume")

            col1, col2 = st.columns([2, 1])
            with col1:
                pdf_bytes, pdf_filename, pdf_error = _ensure_pdf_bytes(session, profile)

                if pdf_bytes:
                    st.markdown("### PDF Preview")
                    _render_pdf_preview(pdf_bytes)
                    st.download_button(
                        label="📕 Download PDF (Ready to Apply)",
                        data=pdf_bytes,
                        file_name=pdf_filename,
                        mime="application/pdf",
                        use_container_width=True,
                        type="primary",
                    )
                else:
                    st.warning(
                        pdf_error
                        or "PDF could not be generated. Install reportlab with "
                        "`.venv\\Scripts\\pip install reportlab` or download Markdown/DOCX below."
                    )

                st.markdown("### Markdown Preview")
                st.markdown(st.session_state.generated_resume)

            with col2:
                st.markdown("### Score & Metrics")
                st.metric("ATS Score", f"{st.session_state.generated_ats_score:.1f}%")
                if st.session_state.generated_missing_keywords:
                    st.info(f"**Missing keywords:** {', '.join(st.session_state.generated_missing_keywords[:5])}")
                if st.session_state.generated_improvements:
                    st.caption(f"**Improvements:** {st.session_state.generated_improvements}")
                export_issues = st.session_state.get("export_validation_issues", [])
                if export_issues:
                    st.warning("**ATS export warnings:**\n- " + "\n- ".join(export_issues))

            st.markdown("### Other Download Options")
            col1, col2 = st.columns(2)

            current_profile = _resolve_profile_for_export(session, profile)

            with col1:
                st.download_button(
                    label="📄 Download Markdown",
                    data=st.session_state.generated_resume,
                    file_name="resume.md",
                    mime="text/markdown",
                    use_container_width=True,
                )

            with col2:
                docx_bytes, docx_issues = _export_docx_with_validation(
                    st.session_state.generated_resume,
                    current_profile,
                    _get_export_keywords(),
                )
                if docx_issues:
                    st.caption(
                        "DOCX ATS notes: " + "; ".join(docx_issues[:3])
                    )
                st.download_button(
                    label="📘 Download DOCX",
                    data=docx_bytes,
                    file_name="resume.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                )

            if st.button("Generate New Resume", use_container_width=True):
                _clear_generated_resume_state()
                st.rerun()

    finally:
        session.close()


if st.session_state.user is None:
    show_auth_screen()
else:
    show_main_app()
