from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure project root is importable when Streamlit runs pages or scripts from subfolders.
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st
from sqlalchemy.orm import Session

from auth.auth_config import authenticate_user, ensure_user_exists, logout
from core.ats_constants import ContactInfo
# Leaf schema modules first (avoid Streamlit partial-import failures).
from core.proposals import ProposedChange
from core.template_config import TemplateConfig, template_config_from_json
from core.profile_schema import ProfileData, profile_data_from_json
from core.cache import get_or_create_job_description
from core.config_loader import get_thresholds
from core.file_parser import parse_uploaded_file
from core.jd_parser import get_priority_keywords
from core.matcher import compute_match_result
from core.pdf_exporter import (
    build_resume_filename,
    generate_docx_bytes,
    generate_pdf_bytes,
)
from core.resume_agent import (
    analyze_tailoring_needs,
    generate_tailored_resume,
    persist_approved_skills_to_master,
    proposals_all_resolved,
)
from core.resume_parser import parse_master_resume, profile_from_legacy_fields
from core.resume_validator import validate_exported_resume
from core.template_extractor import extract_template_config
from db.models import JobDescription, Profile, ResumeVersion, Settings, TailoringSession
from db.session import SessionLocal, init_db

PDF_RENDERER_VERSION = 2

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
    profile = session.query(Profile).filter(Profile.user_id == st.session_state.user.id).first()
    if not profile:
        profile = Profile(user_id=st.session_state.user.id, profile_source="manual")
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
    match_score: float | None = None,
) -> None:
    session = SessionLocal()
    try:
        version = ResumeVersion(
            user_id=user_id,
            job_description_id=job_id,
            markdown_content=markdown_content,
            ats_score=float(ats_score),
            match_score=float(match_score) if match_score is not None else None,
            improvement_summary=improvements,
            missing_keywords=", ".join(missing_keywords),
        )
        session.add(version)
        session.commit()
    finally:
        session.close()


def _get_match_threshold(session: Session) -> int:
    settings = session.query(Settings).filter(Settings.user_id == st.session_state.user.id).first()
    if settings and settings.match_threshold:
        return int(settings.match_threshold)
    return int(get_thresholds().get("match_score", 70))


def _resolve_profile_for_export(session: Session, profile: Profile) -> Profile:
    profile_id = st.session_state.get("generated_profile_id")
    if profile_id:
        stored_profile = session.query(Profile).filter(Profile.id == profile_id).first()
        if stored_profile:
            return stored_profile
    return profile


def _get_export_keywords() -> list[str]:
    return st.session_state.get("generated_priority_keywords", [])


def _get_template_config(profile: Profile) -> TemplateConfig:
    return template_config_from_json(profile.template_config_json)


def _export_pdf_with_validation(
    markdown: str,
    profile: Profile,
    keywords: list[str] | None = None,
    job_title: str | None = None,
    profile_text: str | None = None,
) -> tuple[bytes | None, list[str]]:
    try:
        pdf_bytes = generate_pdf_bytes(
            markdown,
            profile,
            keywords,
            job_title=job_title,
            profile_text=profile_text,
            rewrite_for_one_page=True,
            template_config=_get_template_config(profile),
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
    docx_bytes = generate_docx_bytes(markdown, profile, keywords)
    _, issues = validate_exported_resume(docx_bytes, "docx", keywords)
    return docx_bytes, issues


def _ensure_pdf_bytes(session: Session, profile: Profile) -> tuple[bytes | None, str, str | None]:
    pdf_bytes = st.session_state.get("generated_pdf_bytes")
    pdf_filename = st.session_state.get("generated_pdf_filename", "resume.pdf")
    if pdf_bytes and st.session_state.get("pdf_renderer_version") == PDF_RENDERER_VERSION:
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
    st.session_state.pdf_renderer_version = PDF_RENDERER_VERSION
    return pdf_bytes, pdf_filename, None


def _clear_generated_resume_state() -> None:
    for key in (
        "generated_resume",
        "generated_ats_score",
        "generated_match_score",
        "generated_improvements",
        "generated_missing_keywords",
        "generated_pdf_bytes",
        "generated_pdf_filename",
        "pdf_renderer_version",
        "generated_profile_id",
        "generated_job_title",
        "generated_priority_keywords",
        "export_validation_issues",
        "tailoring_proposals",
        "tailoring_jd_id",
        "tailoring_jd_text",
        "tailoring_session_id",
        "match_gate_acknowledged",
        "current_match_score",
        "current_match_breakdown",
    ):
        if key in st.session_state:
            del st.session_state[key]


def _render_pdf_preview(pdf_bytes: bytes) -> None:
    try:
        st.pdf(pdf_bytes)
    except Exception:
        st.caption("PDF preview unavailable. Use the download button below to open your resume.")


def _render_history_sidebar(session: Session, profile: Profile) -> None:
    st.sidebar.markdown("---")
    st.sidebar.subheader("Resume History")
    versions = (
        session.query(ResumeVersion)
        .filter(ResumeVersion.user_id == st.session_state.user.id)
        .order_by(ResumeVersion.created_at.desc())
        .limit(15)
        .all()
    )
    if not versions:
        st.sidebar.caption("No generated resumes yet.")
        return

    for version in versions:
        jd_title = "Untitled"
        if version.job_description_id:
            jd = session.query(JobDescription).filter(JobDescription.id == version.job_description_id).first()
            if jd and jd.title:
                jd_title = jd.title
        try:
            ats_val = float(version.ats_score or 0)
        except (TypeError, ValueError):
            ats_val = 0.0
        label = f"{jd_title[:28]} · ATS {ats_val:.0f}%"
        with st.sidebar.expander(label):
            st.caption(version.created_at.strftime("%Y-%m-%d %H:%M") if version.created_at else "")
            if version.match_score is not None:
                try:
                    match_val = float(version.match_score)
                except (TypeError, ValueError):
                    match_val = 0.0
                st.write(f"Match: {match_val:.0f}%")
            if st.button("Load", key=f"hist_load_{version.id}", use_container_width=True):
                st.session_state.generated_resume = version.markdown_content
                st.session_state.generated_ats_score = ats_val
                try:
                    st.session_state.generated_match_score = (
                        float(version.match_score) if version.match_score is not None else None
                    )
                except (TypeError, ValueError):
                    st.session_state.generated_match_score = None
                st.session_state.generated_improvements = version.improvement_summary or ""
                st.session_state.generated_missing_keywords = (
                    [k.strip() for k in (version.missing_keywords or "").split(",") if k.strip()]
                )
                st.session_state.generated_profile_id = profile.id
                st.session_state.generated_job_title = jd_title
                st.session_state.generated_pdf_bytes = None
                st.rerun()


def _render_master_resume_section(session: Session, profile: Profile) -> ProfileData | None:
    st.header("1. Master Resume")
    st.write(
        "Upload a multi-page master resume (PDF, DOCX, or TXT). "
        "We extract all experience and template style cues. Review before saving."
    )

    uploaded = st.file_uploader(
        "Upload master resume",
        type=["pdf", "docx", "txt"],
        key="master_resume_upload",
    )
    if uploaded is not None and st.button("Parse Master Resume", use_container_width=True):
        with st.spinner("Parsing master resume and extracting template..."):
            try:
                file_bytes = uploaded.getvalue()
                # Reset stream for parse_uploaded_file
                uploaded.seek(0)
                raw_text = parse_uploaded_file(uploaded)
                data = parse_master_resume(raw_text)
                docx_bytes = file_bytes if uploaded.name.lower().endswith(".docx") else None
                template = extract_template_config(raw_text, docx_bytes=docx_bytes)
                st.session_state.parsed_profile_data = data.model_dump()
                st.session_state.parsed_template_config = template.model_dump()
                st.session_state.parsed_master_raw = raw_text
                st.session_state.parsed_master_filename = uploaded.name
                st.success("Master resume parsed. Review and save below.")
            except Exception as exc:
                st.error(f"Failed to parse master resume: {exc}")

    # Prefer freshly parsed data, else load saved
    pending = st.session_state.get("parsed_profile_data")
    if pending:
        data = ProfileData.model_validate(pending)
    else:
        data = load_profile_data(profile)

    if data is None:
        st.info("No master resume yet. Upload one, or fill the manual form below.")
        with st.form("manual_profile_form"):
            col1, col2 = st.columns(2)
            with col1:
                full_name = st.text_input("Full Name", value=profile.full_name or "")
                email = st.text_input("Email", value=profile.email or "")
                phone = st.text_input("Phone", value=profile.phone or "")
            with col2:
                location = st.text_input("Location", value=profile.location or "")
                linkedin = st.text_input("LinkedIn (optional)", value=profile.linkedin or "")
                github = st.text_input("GitHub (optional)", value=profile.github or "")
            summary = st.text_area("Professional Summary", value=profile.summary or "", height=80)
            skills = st.text_area("Skills", value=profile.skills or "", height=80)
            experience = st.text_area("Experience", value=profile.experience or "", height=100)
            education = st.text_area("Education", value=profile.education or "", height=80)
            if st.form_submit_button("Save Manual Profile", use_container_width=True):
                manual = profile_from_legacy_fields(
                    full_name=full_name,
                    email=email,
                    phone=phone,
                    location=location,
                    linkedin=linkedin,
                    github=github,
                    summary=summary,
                    skills=skills,
                    experience=experience,
                    education=education,
                )
                apply_profile_data_to_model(profile, manual, source="manual")
                profile.template_config_json = TemplateConfig().model_dump_json()
                session.commit()
                st.success("Profile saved.")
                st.rerun()
        return load_profile_data(profile)

    with st.expander("Review structured profile", expanded=True):
        with st.form("review_profile_form"):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("Full Name", value=data.contact.name)
                email = st.text_input("Email", value=data.contact.email)
                phone = st.text_input("Phone", value=data.contact.phone)
            with col2:
                location = st.text_input("Location", value=data.contact.location)
                linkedin = st.text_input("LinkedIn", value=data.contact.linkedin)
                github = st.text_input("GitHub", value=data.contact.github)
            summary = st.text_area("Summary", value=data.summary, height=80)
            skills = st.text_area("Skills (comma-separated)", value=", ".join(data.skills), height=80)
            experience_preview = st.text_area(
                "Experience preview (read-only summary)",
                value="\n\n".join(
                    f"{e.title} @ {e.company} ({e.start_date} - {e.end_date})\n"
                    + "\n".join(f"- {b}" for b in e.bullets[:4])
                    for e in data.experience
                ),
                height=160,
                disabled=True,
            )
            st.caption(f"{len(data.experience)} roles · {len(data.skills)} skills · {len(data.education)} education entries")
            save = st.form_submit_button("Save Master Profile", use_container_width=True, type="primary")
            if save:
                skill_list = [s.strip() for s in skills.split(",") if s.strip()]
                updated = data.model_copy(
                    update={
                        "summary": summary,
                        "skills": skill_list,
                        "contact": ContactInfo(
                            name=name,
                            email=email,
                            phone=phone,
                            location=location,
                            linkedin=linkedin,
                            github=github,
                            portfolio=data.contact.portfolio,
                        ),
                    }
                )
                apply_profile_data_to_model(
                    profile,
                    updated,
                    source="upload" if st.session_state.get("parsed_master_raw") else (profile.profile_source or "hybrid"),
                )
                if st.session_state.get("parsed_master_raw"):
                    profile.master_resume_raw_text = st.session_state.parsed_master_raw
                    profile.master_resume_filename = st.session_state.get("parsed_master_filename")
                if st.session_state.get("parsed_template_config"):
                    profile.template_config_json = json.dumps(st.session_state.parsed_template_config)
                elif not profile.template_config_json:
                    profile.template_config_json = TemplateConfig().model_dump_json()
                session.commit()
                for key in ("parsed_profile_data", "parsed_template_config", "parsed_master_raw", "parsed_master_filename"):
                    st.session_state.pop(key, None)
                st.success("Master profile saved.")
                st.rerun()

    if profile.master_resume_filename:
        st.caption(f"Source file: {profile.master_resume_filename} · source={profile.profile_source or 'manual'}")
    cfg = _get_template_config(profile)
    st.caption(
        f"Template: {' → '.join(cfg.section_order[:5])} · color {cfg.primary_color} · font {cfg.font_family}"
    )
    return load_profile_data(profile)


def _update_proposal_status(proposal_id: str, status: str, *, suggested_text: str | None = None, persist: bool = False) -> None:
    proposals = [ProposedChange.model_validate(p) for p in st.session_state.get("tailoring_proposals", [])]
    updated: list[dict] = []
    for proposal in proposals:
        if proposal.id == proposal_id:
            data = proposal.model_dump()
            data["status"] = status
            if suggested_text is not None:
                data["suggested_text"] = suggested_text
                if status == "approved":
                    data["status"] = "edited" if suggested_text != proposal.suggested_text else "approved"
            data["persist_to_master"] = persist
            updated.append(data)
        else:
            updated.append(proposal.model_dump())
    st.session_state.tailoring_proposals = updated


def _render_proposals_ui() -> list[ProposedChange]:
    proposals = [ProposedChange.model_validate(p) for p in st.session_state.get("tailoring_proposals", [])]
    if not proposals:
        return []

    approved = sum(1 for p in proposals if p.status in ("approved", "edited"))
    rejected = sum(1 for p in proposals if p.status == "rejected")
    pending = sum(1 for p in proposals if p.status == "pending")
    st.info(f"Proposals: **{approved}** approved · **{rejected}** rejected · **{pending}** pending")

    for proposal in proposals:
        badge = "⚠️" if proposal.requires_confirmation and not proposal.grounded_in_profile else "✓"
        status_label = proposal.status.upper()
        with st.container(border=True):
            st.markdown(f"{badge} **{proposal.description}** · `{proposal.type}` · **{status_label}**")
            if proposal.suggested_text:
                st.caption(f"Suggested: {proposal.suggested_text}")
            if proposal.jd_evidence:
                st.caption(f"JD evidence: {proposal.jd_evidence}")
            if not proposal.grounded_in_profile:
                st.warning("Not found in your master resume — confirmation required.")

            if proposal.status == "pending":
                c1, c2, c3 = st.columns(3)
                with c1:
                    if st.button("Approve", key=f"approve_{proposal.id}", use_container_width=True):
                        persist = False
                        _update_proposal_status(proposal.id, "approved", persist=persist)
                        st.rerun()
                with c2:
                    if st.button("Reject", key=f"reject_{proposal.id}", use_container_width=True):
                        _update_proposal_status(proposal.id, "rejected")
                        st.rerun()
                with c3:
                    edit_key = f"edit_toggle_{proposal.id}"
                    if st.button("Edit & Approve", key=edit_key, use_container_width=True):
                        st.session_state[f"editing_{proposal.id}"] = True
                        st.rerun()

                if st.session_state.get(f"editing_{proposal.id}"):
                    edited = st.text_input(
                        "Edited text",
                        value=proposal.suggested_text,
                        key=f"edit_text_{proposal.id}",
                    )
                    persist = False
                    if proposal.type == "add_skill":
                        persist = st.checkbox(
                            "Also add to master profile for future JDs",
                            key=f"persist_{proposal.id}",
                        )
                    if st.button("Save & Approve", key=f"save_edit_{proposal.id}"):
                        _update_proposal_status(
                            proposal.id,
                            "edited",
                            suggested_text=edited,
                            persist=persist,
                        )
                        st.session_state.pop(f"editing_{proposal.id}", None)
                        st.rerun()
            elif proposal.type == "add_skill" and proposal.status in ("approved", "edited"):
                persist = st.checkbox(
                    "Add to master profile",
                    value=proposal.persist_to_master,
                    key=f"persist_saved_{proposal.id}",
                )
                if persist != proposal.persist_to_master:
                    _update_proposal_status(
                        proposal.id,
                        proposal.status,
                        suggested_text=proposal.suggested_text,
                        persist=persist,
                    )

    return [ProposedChange.model_validate(p) for p in st.session_state.get("tailoring_proposals", [])]


def _persist_tailoring_session(
    session: Session,
    *,
    jd_id: int | None,
    status: str,
    proposals: list[ProposedChange],
    markdown: str | None = None,
    match_score: float | None = None,
) -> None:
    session_id = st.session_state.get("tailoring_session_id")
    row = None
    if session_id:
        row = session.query(TailoringSession).filter(TailoringSession.id == session_id).first()
    if row is None:
        row = TailoringSession(user_id=st.session_state.user.id)
        session.add(row)
    row.job_description_id = jd_id
    row.status = status
    row.proposals_json = json.dumps([p.model_dump() for p in proposals])
    if markdown is not None:
        row.approved_resume_markdown = markdown
    if match_score is not None:
        row.match_score = match_score
    session.commit()
    session.refresh(row)
    st.session_state.tailoring_session_id = row.id


def show_main_app() -> None:
    st.title("Joba Resume Tailoring")
    st.caption("Master resume → JD agent confirmations → single-page ATS PDF")

    st.sidebar.title("Account")
    st.sidebar.write(f"**{st.session_state.user.username}**")
    st.sidebar.button("Log out", on_click=logout, use_container_width=True)

    session = SessionLocal()
    try:
        profile = get_or_create_profile(session)
        _render_history_sidebar(session, profile)

        profile_data = _render_master_resume_section(session, profile)

        st.divider()
        st.header("2. Target Job")
        st.write("Paste or upload the job description you're applying for.")

        jd_input_method = st.radio(
            "JD Input Method",
            ["Paste Text", "Upload File"],
            horizontal=True,
            key="jd_input_method",
        )
        jd_title = st.text_input("Job Title (optional)", key="jd_title")
        jd_text = ""
        if jd_input_method == "Paste Text":
            jd_text = st.text_area("Job Description", height=150, key="jd_paste")
        else:
            uploaded_file = st.file_uploader(
                "Upload Job Description (PDF, DOCX, or TXT)",
                type=["pdf", "docx", "txt"],
                key="jd_upload",
            )
            if uploaded_file is not None:
                try:
                    jd_text = parse_uploaded_file(uploaded_file)
                    st.success("File parsed successfully")
                except Exception as e:
                    st.error(f"Failed to parse file: {e}")

        st.divider()
        st.header("3. Tailoring Agent")
        st.write(
            "The agent compares your master resume to the JD and asks for confirmation "
            "before adding anything not already in your profile."
        )

        if st.button("Analyze JD & Propose Changes", use_container_width=True, type="primary"):
            if profile_data is None:
                st.error("Save a master profile first.")
            elif not jd_text.strip():
                st.error("Provide a job description.")
            else:
                with st.spinner("Parsing JD and analyzing gaps..."):
                    try:
                        jd_record = get_or_create_job_description(
                            session,
                            st.session_state.user.id,
                            jd_text,
                            jd_title or "Untitled role",
                        )
                        match_result = compute_match_result(
                            profile_data, jd_text, jd=jd_record
                        )
                        match_score = match_result.score
                        proposals = analyze_tailoring_needs(profile_data, jd_text, jd=jd_record)
                        st.session_state.tailoring_proposals = [p.model_dump() for p in proposals]
                        st.session_state.tailoring_jd_id = jd_record.id
                        st.session_state.tailoring_jd_text = jd_text
                        st.session_state.current_match_score = match_score
                        st.session_state.current_match_breakdown = {
                            "matched_required": match_result.matched_required,
                            "missing_required": match_result.missing_required,
                            "matched_preferred": match_result.matched_preferred,
                            "missing_preferred": match_result.missing_preferred,
                            "components": match_result.components,
                        }
                        st.session_state.match_gate_acknowledged = False
                        _persist_tailoring_session(
                            session,
                            jd_id=jd_record.id,
                            status="awaiting_confirmation",
                            proposals=proposals,
                            match_score=match_score,
                        )
                        st.success(f"Found {len(proposals)} proposals. Match score: {match_score:.0f}%")
                        st.rerun()
                    except Exception as exc:
                        session.rollback()
                        st.error(f"Analysis failed: {exc}")

        match_score = st.session_state.get("current_match_score")
        if match_score is not None:
            threshold = _get_match_threshold(session)
            st.metric("Profile–JD Match", f"{match_score:.0f}%")
            breakdown = st.session_state.get("current_match_breakdown") or {}
            with st.expander("Match breakdown", expanded=False):
                comps = breakdown.get("components") or {}
                if comps:
                    parts = []
                    for key in ("required", "preferred", "title", "years"):
                        val = comps.get(key)
                        if val is not None:
                            parts.append(f"{key.title()}: {val:.0f}%")
                    if parts:
                        st.caption(" · ".join(parts))
                matched_req = breakdown.get("matched_required") or []
                missing_req = breakdown.get("missing_required") or []
                matched_pref = breakdown.get("matched_preferred") or []
                if matched_req:
                    st.caption("Matched required: " + ", ".join(matched_req[:12]))
                if missing_req:
                    st.caption("Missing required: " + ", ".join(missing_req[:12]))
                if matched_pref:
                    st.caption("Matched preferred: " + ", ".join(matched_pref[:12]))
            if match_score < threshold and not st.session_state.get("match_gate_acknowledged"):
                st.warning(
                    f"Match score is below your threshold ({threshold}%). "
                    "This role may be a weak fit. Acknowledge to continue."
                )
                if st.button("Acknowledge low match and continue", use_container_width=True):
                    st.session_state.match_gate_acknowledged = True
                    st.rerun()
            elif match_score < threshold:
                st.caption(f"Low match acknowledged (threshold {threshold}%).")

        proposals = _render_proposals_ui()

        can_generate = bool(proposals) and proposals_all_resolved(proposals)
        threshold = _get_match_threshold(session)
        if match_score is not None and match_score < threshold and not st.session_state.get("match_gate_acknowledged"):
            can_generate = False

        if st.button(
            "Generate Tailored Resume",
            use_container_width=True,
            type="primary",
            disabled=not can_generate,
        ):
            if profile_data is None:
                st.error("Master profile missing.")
            else:
                with st.spinner("Generating constrained resume and one-page PDF..."):
                    try:
                        jd_id = st.session_state.get("tailoring_jd_id")
                        jd_record = (
                            session.query(JobDescription).filter(JobDescription.id == jd_id).first()
                            if jd_id
                            else None
                        )
                        jd_text_final = st.session_state.get("tailoring_jd_text") or jd_text
                        thresholds = get_thresholds()
                        result = generate_tailored_resume(
                            profile_data,
                            jd_text_final,
                            proposals,
                            jd=jd_record,
                            template_config=_get_template_config(profile),
                            max_iterations=int(thresholds["max_iterations"]),
                        )

                        # Persist approved skills to master if requested
                        updated_master = persist_approved_skills_to_master(profile_data, proposals)
                        if updated_master.skills != profile_data.skills:
                            apply_profile_data_to_model(profile, updated_master, source="hybrid")
                            session.commit()

                        markdown_content = result["markdown_content"]
                        ats_score = result["ats_score"]
                        improvements = result["improvements"]
                        missing_keywords = result["missing_keywords"]
                        gen_match = result.get("match_score", match_score)

                        priority_keywords = get_priority_keywords(jd_record) if jd_record else []
                        generated_job_title = (
                            (jd_record.title if jd_record else None) or jd_title or "Job"
                        )
                        try:
                            pdf_bytes, export_issues = _export_pdf_with_validation(
                                markdown_content,
                                profile,
                                priority_keywords,
                                generated_job_title,
                                build_profile_text(profile),
                            )
                        except Exception as exc:
                            st.warning(f"Resume saved, but PDF export failed: {exc}")
                            pdf_bytes = None
                            export_issues = []

                        pdf_filename = build_resume_filename(profile, generated_job_title)
                        save_resume_to_db(
                            st.session_state.user.id,
                            jd_record.id if jd_record else None,
                            markdown_content,
                            ats_score,
                            improvements,
                            missing_keywords,
                            match_score=gen_match,
                        )
                        _persist_tailoring_session(
                            session,
                            jd_id=jd_record.id if jd_record else None,
                            status="complete",
                            proposals=proposals,
                            markdown=markdown_content,
                            match_score=gen_match,
                        )

                        st.session_state.generated_resume = markdown_content
                        st.session_state.generated_ats_score = ats_score
                        st.session_state.generated_match_score = gen_match
                        st.session_state.generated_improvements = improvements
                        st.session_state.generated_missing_keywords = missing_keywords
                        st.session_state.generated_pdf_bytes = pdf_bytes
                        st.session_state.generated_pdf_filename = pdf_filename
                        st.session_state.pdf_renderer_version = PDF_RENDERER_VERSION
                        st.session_state.generated_profile_id = profile.id
                        st.session_state.generated_job_title = generated_job_title
                        st.session_state.generated_priority_keywords = priority_keywords
                        st.session_state.export_validation_issues = export_issues
                        st.success("Resume generated and saved!")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Error generating resume: {exc}")

        if proposals and not proposals_all_resolved(proposals):
            st.caption("Resolve all pending proposals before generating.")

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
                        label="Download PDF (Ready to Apply)",
                        data=pdf_bytes,
                        file_name=pdf_filename,
                        mime="application/pdf",
                        use_container_width=True,
                        type="primary",
                    )
                else:
                    st.warning(
                        pdf_error
                        or "PDF could not be generated. Install reportlab or download Markdown/DOCX below."
                    )
                st.markdown("### Markdown Preview")
                st.markdown(st.session_state.generated_resume)

            with col2:
                st.markdown("### Score & Metrics")
                st.metric("ATS Score", f"{st.session_state.generated_ats_score:.1f}%")
                if st.session_state.get("generated_match_score") is not None:
                    st.metric("Match Score", f"{st.session_state.generated_match_score:.1f}%")
                if st.session_state.generated_missing_keywords:
                    st.info(
                        "**Missing keywords:** "
                        + ", ".join(st.session_state.generated_missing_keywords[:5])
                    )
                if st.session_state.generated_improvements:
                    st.caption(f"**Improvements:** {st.session_state.generated_improvements}")
                export_issues = st.session_state.get("export_validation_issues", [])
                if export_issues:
                    st.warning("**ATS export warnings:**\n- " + "\n- ".join(export_issues))

            st.markdown("### Other Download Options")
            c1, c2 = st.columns(2)
            current_profile = _resolve_profile_for_export(session, profile)
            with c1:
                st.download_button(
                    label="Download Markdown",
                    data=st.session_state.generated_resume,
                    file_name="resume.md",
                    mime="text/markdown",
                    use_container_width=True,
                )
            with c2:
                docx_bytes, docx_issues = _export_docx_with_validation(
                    st.session_state.generated_resume,
                    current_profile,
                    _get_export_keywords(),
                )
                if docx_issues:
                    st.caption("DOCX ATS notes: " + "; ".join(docx_issues[:3]))
                st.download_button(
                    label="Download DOCX",
                    data=docx_bytes,
                    file_name="resume.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                )

            if st.button("Start New Tailoring Session", use_container_width=True):
                _clear_generated_resume_state()
                st.rerun()
    finally:
        session.close()


if st.session_state.user is None:
    show_auth_screen()
else:
    show_main_app()
