from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Streamlit keeps stale local modules in sys.modules across reruns, which
# raises ImportError/KeyError for names added after the first load.
for _name in list(sys.modules):
    if _name == "core" or _name.startswith("core."):
        sys.modules.pop(_name, None)

import streamlit as st
from datetime import datetime
from sqlalchemy.orm import Session

from auth.auth_config import authenticate_user, ensure_user_exists, logout
from core.ats_constants import ContactInfo
from core.file_parser import parse_uploaded_file, strip_html_to_text
from core.job_source import fetch_job_posting
from core.resume_parser import parse_master_resume, profile_from_legacy_fields
from core.services.export_service import export_docx, export_pdf, resume_filename
from core.services.profile_service import (
    apply_profile_data_to_model,
    build_profile_text,
    get_or_create_profile,
    get_template_config,
    load_profile_data,
    save_master_profile,
)
from core.services.tailoring_service import run_tailoring_workflow
from core.services.job_discovery_service import (
    list_job_listings,
    run_job_search,
    update_job_status,
)
from core.template_config import TemplateConfig
from core.template_extractor import extract_template_config
from core.profile_schema import ProfileData
from db.models import JobDescription, Profile, ResumeVersion
from db.session import SessionLocal, init_db

PDF_RENDERER_VERSION = 2

st.set_page_config(page_title="Joba", page_icon="💼", layout="wide")

st.markdown(
    """
    <style>
    :root { color-scheme: dark; }
    html, body, [data-testid="stAppViewContainer"], .stApp {
        background-color: #0e1117;
        color: #e8eef6;
    }
    [data-testid="stHeader"] {
        background: rgba(14, 17, 23, 0.85);
    }
    [data-testid="stSidebar"], [data-testid="stSidebarContent"] {
        background-color: #131820;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

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


def _clear_generated_resume_state() -> None:
    for key in (
        "generated_resume",
        "generated_ats_score",
        "generated_match_score",
        "generated_match_components",
        "generated_improvements",
        "generated_missing_keywords",
        "generated_pdf_bytes",
        "generated_pdf_filename",
        "pdf_renderer_version",
        "generated_profile_id",
        "generated_job_title",
        "generated_priority_keywords",
        "export_validation_issues",
        "export_blocked",
        "tailoring_jd_text",
        "tailoring_session_id",
        "evidence_count",
        "agent_progress",
    ):
        st.session_state.pop(key, None)


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
                st.session_state.generated_missing_keywords = [
                    k.strip() for k in (version.missing_keywords or "").split(",") if k.strip()
                ]
                st.session_state.generated_profile_id = profile.id
                st.session_state.generated_job_title = jd_title
                st.session_state.generated_pdf_bytes = None
                st.rerun()


def _render_master_resume_section(session: Session, profile: Profile) -> ProfileData | None:
    st.header("1. Master Resume")
    st.write(
        "Upload a multi-page master resume (PDF, DOCX, or TXT). "
        "We extract all experience, index evidence in Chroma, and capture template style cues."
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
                chunks = save_master_profile(
                    session,
                    profile,
                    manual,
                    source="manual",
                    template_config=TemplateConfig(),
                    reindex=True,
                )
                st.success(f"Profile saved. Indexed {chunks} evidence chunks in Chroma.")
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
            st.text_area(
                "Experience preview (read-only summary)",
                value="\n\n".join(
                    f"{e.title} @ {e.company} ({e.start_date} - {e.end_date})\n"
                    + "\n".join(f"- {b}" for b in e.bullets[:4])
                    for e in data.experience
                ),
                height=160,
                disabled=True,
            )
            st.caption(
                f"{len(data.experience)} roles · {len(data.skills)} skills · {len(data.education)} education entries"
            )
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
                template = None
                if st.session_state.get("parsed_template_config"):
                    template = TemplateConfig.model_validate(st.session_state.parsed_template_config)
                chunks = save_master_profile(
                    session,
                    profile,
                    updated,
                    source="upload" if st.session_state.get("parsed_master_raw") else (
                        profile.profile_source or "hybrid"
                    ),
                    raw_text=st.session_state.get("parsed_master_raw"),
                    filename=st.session_state.get("parsed_master_filename"),
                    template_config=template,
                    reindex=True,
                )
                for key in (
                    "parsed_profile_data",
                    "parsed_template_config",
                    "parsed_master_raw",
                    "parsed_master_filename",
                ):
                    st.session_state.pop(key, None)
                st.success(f"Master profile saved. Indexed {chunks} evidence chunks in Chroma.")
                st.rerun()

    if profile.master_resume_filename:
        st.caption(
            f"Source file: {profile.master_resume_filename} · source={profile.profile_source or 'manual'}"
        )
    cfg = get_template_config(profile)
    st.caption(
        f"Template: {' → '.join(cfg.section_order[:5])} · color {cfg.primary_color} · font {cfg.font_family}"
    )
    return load_profile_data(profile)


def _render_agent_progress(container, progress: dict[str, dict[str, str]]) -> None:
    labels = {
        "job_research": "Job research",
        "candidate_profiling": "Candidate profiling",
        "resume_strategy": "Resume strategy",
    }
    icons = {
        "queued": "◯",
        "running": "◐",
        "completed": "✓",
        "failed": "!",
    }
    with container.container():
        st.subheader("Agent task progress")
        for name, label in labels.items():
            state = progress.get(name, {"status": "queued", "detail": ""})
            st.write(f"{icons.get(state['status'], '◯')} **{label}:** {state['status'].title()}")
            if state.get("detail"):
                st.caption(state["detail"])


def _ensure_pdf_bytes(session: Session, profile: Profile) -> tuple[bytes | None, str, str | None]:
    pdf_bytes = st.session_state.get("generated_pdf_bytes")
    pdf_filename = st.session_state.get("generated_pdf_filename", "resume.pdf")
    if pdf_bytes and st.session_state.get("pdf_renderer_version") == PDF_RENDERER_VERSION:
        return pdf_bytes, pdf_filename, st.session_state.get("export_block_error")

    markdown = st.session_state.get("generated_resume")
    if not markdown:
        return None, pdf_filename, "No resume content available."

    profile_id = st.session_state.get("generated_profile_id")
    export_profile = profile
    if profile_id:
        stored = session.query(Profile).filter(Profile.id == profile_id).first()
        if stored:
            export_profile = stored

    keywords = st.session_state.get("generated_priority_keywords", [])
    pdf_bytes, issues, error = export_pdf(
        markdown,
        export_profile,
        keywords,
        job_title=st.session_state.get("generated_job_title"),
        profile_text=build_profile_text(export_profile),
        block_on_issues=True,
    )
    st.session_state.export_validation_issues = issues
    st.session_state.export_block_error = error
    st.session_state.export_blocked = bool(error)
    if pdf_bytes:
        pdf_filename = resume_filename(
            export_profile,
            st.session_state.get("generated_job_title", "Job"),
        )
        st.session_state.generated_pdf_bytes = pdf_bytes
        st.session_state.generated_pdf_filename = pdf_filename
        st.session_state.pdf_renderer_version = PDF_RENDERER_VERSION
    return pdf_bytes, pdf_filename, error


def show_main_app() -> None:
    st.title("Joba Resume Tailoring")
    st.caption("Master resume + job description → three-agent tailoring workflow → ATS-validated resume")

    st.sidebar.title("Account")
    st.sidebar.write(f"**{st.session_state.user.username}**")
    st.sidebar.button("Log out", on_click=logout, use_container_width=True)

    session = SessionLocal()
    try:
        profile = get_or_create_profile(session, st.session_state.user.id)
        _render_history_sidebar(session, profile)

        profile_data = _render_master_resume_section(session, profile)

        st.divider()
        st.header("2. Target Job")
        st.write("Paste the job description, provide a public posting link, or upload a document.")

        jd_input_method = st.radio(
            "JD Input Method",
            ["Paste Text", "Job Posting URL", "Upload File"],
            horizontal=True,
            key="jd_input_method",
        )
        jd_title = st.text_input("Job Title (optional)", key="jd_title")
        jd_text = ""
        jd_source_url = None
        if jd_input_method == "Paste Text":
            raw_paste = st.text_area("Job Description", height=150, key="jd_paste")
            jd_text = strip_html_to_text(raw_paste)
            if raw_paste and raw_paste != jd_text and "<" in raw_paste:
                st.caption("Detected HTML/LinkedIn paste — cleaned to plain text.")
        elif jd_input_method == "Job Posting URL":
            jd_source_url = st.text_input(
                "Public HTTPS job posting URL",
                placeholder="https://jobs.example.com/role",
                key="jd_source_url",
            ).strip()
        else:
            uploaded_file = st.file_uploader(
                "Upload Job Description (PDF, DOCX, or TXT)",
                type=["pdf", "docx", "txt", "html", "htm"],
                key="jd_upload",
            )
            if uploaded_file is not None:
                try:
                    jd_text = parse_uploaded_file(uploaded_file)
                    st.success("File parsed successfully")
                except Exception as e:
                    st.error(f"Failed to parse file: {e}")

        st.divider()
        st.header("3. AI Resume Tailoring")
        st.write(
            "Job research and candidate profiling run in parallel. A resume strategist then selects "
            "and orders facts from your master profile; it cannot add new skills, roles, or bullet text."
        )

        progress_placeholder = st.empty()
        existing_progress = st.session_state.get("agent_progress")
        if existing_progress:
            _render_agent_progress(progress_placeholder, existing_progress)

        if st.button("Tailor Resume", use_container_width=True, type="primary"):
            if profile_data is None:
                st.error("Save a master profile first.")
            elif jd_input_method == "Job Posting URL" and not jd_source_url:
                st.error("Provide a job posting URL.")
            elif jd_input_method != "Job Posting URL" and not jd_text.strip():
                st.error("Provide a job description.")
            else:
                _clear_generated_resume_state()
                if jd_input_method == "Job Posting URL":
                    try:
                        with st.spinner("Fetching the job posting..."):
                            jd_text = fetch_job_posting(jd_source_url or "")
                    except Exception as exc:
                        st.error(f"Could not read the job posting: {exc}")

                if jd_text.strip():
                    progress = {
                        "job_research": {"status": "queued", "detail": ""},
                        "candidate_profiling": {"status": "queued", "detail": ""},
                        "resume_strategy": {"status": "queued", "detail": ""},
                    }
                    st.session_state.agent_progress = progress
                    _render_agent_progress(progress_placeholder, progress)

                    def on_progress(updated: dict[str, dict[str, str]]) -> None:
                        st.session_state.agent_progress = updated
                        _render_agent_progress(progress_placeholder, updated)

                    try:
                        result = run_tailoring_workflow(
                            session,
                            user_id=st.session_state.user.id,
                            profile=profile,
                            profile_data=profile_data,
                            jd_text=jd_text,
                            jd_title=jd_title or "Untitled role",
                            jd_source_url=jd_source_url,
                            template_config=get_template_config(profile),
                            progress_callback=on_progress,
                        )
                        st.session_state.generated_resume = result["markdown_content"]
                        st.session_state.generated_ats_score = result["ats_score"]
                        st.session_state.generated_match_score = result["match_score"]
                        st.session_state.generated_match_components = result["match_components"]
                        st.session_state.generated_improvements = result["improvements"]
                        st.session_state.generated_missing_keywords = result["missing_keywords"]
                        st.session_state.generated_priority_keywords = result["priority_keywords"]
                        st.session_state.generated_job_title = result["job_title"]
                        st.session_state.generated_profile_id = result["profile_id"]
                        st.session_state.generated_pdf_bytes = None
                        st.session_state.tailoring_jd_text = jd_text
                        st.session_state.tailoring_session_id = result["session_id"]
                        st.session_state.evidence_count = result["evidence_count"]
                        st.success(
                            f"Resume tailored and saved. Match {result['match_score']:.0f}% · "
                            f"{result['evidence_count']} evidence hits."
                        )
                        st.rerun()
                    except Exception as exc:
                        session.rollback()
                        st.error(f"Resume tailoring failed: {exc}")

        match_score = st.session_state.get("generated_match_score")
        if match_score is not None:
            st.metric("Profile–JD Match", f"{match_score:.0f}%")
            comps = st.session_state.get("generated_match_components") or {}
            if comps:
                parts = [
                    f"{k}: {v:.0f}%" if isinstance(v, (int, float)) else f"{k}: n/a"
                    for k, v in comps.items()
                ]
                st.caption(" · ".join(parts))
            if st.session_state.get("evidence_count"):
                st.caption(f"Retrieved evidence hits: {st.session_state.evidence_count}")

        st.divider()
        if "generated_resume" in st.session_state and st.session_state.generated_resume:
            st.header("4. Your Tailored Resume")
            col1, col2 = st.columns([2, 1])
            with col1:
                pdf_bytes, pdf_filename, pdf_error = _ensure_pdf_bytes(session, profile)
                if pdf_bytes:
                    st.markdown("### PDF Preview")
                    _render_pdf_preview(pdf_bytes)
                    if pdf_error:
                        st.error(pdf_error)
                        st.caption("Fix validation issues before treating this as ready-to-apply.")
                    else:
                        st.download_button(
                            label="Download PDF (Ready to Apply)",
                            data=pdf_bytes,
                            file_name=pdf_filename,
                            mime="application/pdf",
                            use_container_width=True,
                            type="primary",
                        )
                    if pdf_error:
                        st.download_button(
                            label="Download PDF anyway (not validated)",
                            data=pdf_bytes,
                            file_name=pdf_filename,
                            mime="application/pdf",
                            use_container_width=True,
                        )
                else:
                    st.warning(pdf_error or "PDF could not be generated.")
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
            with c1:
                st.download_button(
                    label="Download Markdown",
                    data=st.session_state.generated_resume,
                    file_name="resume.md",
                    mime="text/markdown",
                    use_container_width=True,
                )
            with c2:
                docx_bytes, docx_issues, _ = export_docx(
                    st.session_state.generated_resume,
                    profile,
                    st.session_state.get("generated_priority_keywords", []),
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



def _render_find_jobs_tab() -> None:
    st.header("Find Jobs")
    st.write("Search approved public job sources, compare fresh postings with your master profile, and apply manually.")
    try:
        from core.llm_client import llm_client
        provider, model, _api_key = llm_client.get_runtime_settings()
        if provider == "ollama":
            st.warning(f"Ollama model `{model}` may not reliably use tools. Joba will use deterministic search and scoring if the agent workflow cannot complete.")
    except Exception as exc:
        st.warning(f"Could not determine the configured agent model: {exc}")

    with st.form("job_search_form"):
        col_location, col_remote = st.columns([2, 1])
        with col_location:
            location = st.text_input("Location", value="", placeholder="City, region, or country")
        with col_remote:
            remote_only = st.checkbox("Remote only", value=False)
        col_age, col_count = st.columns(2)
        with col_age:
            max_age_days = st.number_input("Maximum posting age (days)", min_value=1, max_value=365, value=14)
        with col_count:
            top_n = st.number_input("Number of results", min_value=1, max_value=20, value=10)
        submitted = st.form_submit_button("Find Jobs", type="primary", use_container_width=True)

    progress_placeholder = st.empty()
    previous_progress = st.session_state.get("job_search_progress")
    if previous_progress:
        _render_discovery_progress(progress_placeholder, previous_progress)
    if submitted:
        progress = {
            "query_planner": {"status": "queued", "detail": ""},
            "job_scout": {"status": "queued", "detail": ""},
            "fit_analyst": {"status": "queued", "detail": ""},
        }
        st.session_state.job_search_progress = progress
        _render_discovery_progress(progress_placeholder, progress)

        def on_progress(updated: dict[str, dict[str, str]]) -> None:
            st.session_state.job_search_progress = updated
            _render_discovery_progress(progress_placeholder, updated)

        try:
            with st.spinner("Searching public job sources and scoring matches..."):
                output = run_job_search(
                    st.session_state.user.id,
                    location,
                    remote_only,
                    int(max_age_days),
                    int(top_n),
                    progress_callback=on_progress,
                )
            st.session_state.job_search_results = output["results"]
            st.session_state.job_search_report = {
                "fallback_note": output.get("fallback_note"),
                "source_errors": output.get("source_errors", []),
                "candidate_count": output.get("candidate_count", 0),
                "tool_calls": output.get("tool_calls", 0),
                "search_calls": output.get("search_calls", 0),
                "estimated_text_tokens": output.get("estimated_text_tokens", 0),
            }
            st.rerun()
        except Exception as exc:
            st.error(f"Job search failed: {exc}")

    report = st.session_state.get("job_search_report", {})
    if report.get("fallback_note"):
        st.warning(report["fallback_note"])
    for error in report.get("source_errors", []):
        st.warning(error)
    if report:
        st.caption(
            f"{report.get('candidate_count', 0)} validated candidates ? "
            f"{report.get('search_calls', 0)} search calls ? {report.get('tool_calls', 0)} tool calls ? "
            f"about {report.get('estimated_text_tokens', 0)} text tokens processed"
        )

    results = st.session_state.get("job_search_results", [])
    if results:
        st.subheader("Matches")
        for item in results:
            with st.container(border=True):
                title_col, score_col = st.columns([4, 1])
                with title_col:
                    st.markdown(f"### {item['title']}")
                    st.write(f"**{item['company']}** ? {item.get('location') or 'Location not specified'} ? {item.get('source', '').title()}")
                    try:
                        posted = datetime.fromisoformat(item["posted_at"]).strftime("%Y-%m-%d")
                    except (KeyError, ValueError, TypeError):
                        posted = "Date unavailable"
                    st.caption(f"Posted {posted} ? Status: {item.get('status', 'new').title()}")
                with score_col:
                    st.metric("Match", f"{float(item.get('match_score', 0)):.0f}%")
                st.write(item.get("fit_note") or "No fit note available.")
                gaps = item.get("gaps", [])
                if gaps:
                    st.caption("**Potential gaps:** " + ", ".join(str(gap) for gap in gaps[:8]))
                action_cols = st.columns([1, 1, 1, 1, 2])
                with action_cols[0]:
                    st.link_button("Open link", item["url"], use_container_width=True)
                for column, label, status in zip(action_cols[1:4], ("Save", "Applied", "Ignore"), ("saved", "applied", "ignored")):
                    with column:
                        if st.button(label, key=f"job_{status}_{item['id']}", use_container_width=True):
                            _set_job_status(item, status)
                with action_cols[4]:
                    if st.button("Send to Tailor", key=f"job_tailor_{item['id']}", use_container_width=True):
                        st.session_state.jd_input_method = "Paste Text"
                        st.session_state.jd_paste = item.get("jd_text", "")
                        st.session_state.jd_title = item.get("title", "")
                        st.session_state.tailoring_jd_text = item.get("jd_text", "")
                        st.success("Job description filled into the existing tailoring intake. Switch to Tailor Resume to continue.")

    st.divider()
    st.subheader("Saved / History")
    history_status = st.selectbox("Filter by status", ["All except ignored", "New", "Saved", "Applied", "Ignored"], key="job_history_filter")
    filter_map = {"New": "new", "Saved": "saved", "Applied": "applied", "Ignored": "ignored"}
    with SessionLocal() as session:
        history = list_job_listings(session, st.session_state.user.id, filter_map.get(history_status))
    if history_status == "All except ignored":
        history = [row for row in history if row.status != "ignored"]
    if not history:
        st.caption("No job history for this filter yet.")
    for row in history:
        with st.expander(f"{row.match_score or 0:.0f}% ? {row.title} ? {row.company} ({row.status})"):
            st.write(f"{row.location or 'Location not specified'} ? {row.posted_at:%Y-%m-%d} ? {row.source.title()}")
            st.write(row.fit_note or "")
            st.link_button("Open link", row.url)
            status_col, tailor_col = st.columns(2)
            with status_col:
                new_status = st.selectbox("Update status", ["new", "saved", "applied", "ignored"], index=["new", "saved", "applied", "ignored"].index(row.status), key=f"hist_status_{row.id}")
                if st.button("Update", key=f"hist_update_{row.id}"):
                    try:
                        with SessionLocal() as session:
                            update_job_status(session, st.session_state.user.id, row.id, new_status)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not update status: {exc}")
            with tailor_col:
                if st.button("Send to Tailor", key=f"hist_tailor_{row.id}"):
                    st.session_state.jd_input_method = "Paste Text"
                    st.session_state.jd_paste = row.jd_text or ""
                    st.session_state.jd_title = row.title
                    st.success("Description filled into tailoring intake. Switch to Tailor Resume to continue.")


def _render_discovery_progress(container, progress: dict[str, dict[str, str]]) -> None:
    labels = {"query_planner": "Query planner", "job_scout": "Job scout", "fit_analyst": "Fit analyst"}
    icons = {"queued": "?", "running": "?", "completed": "?", "failed": "!"}
    with container.container():
        st.subheader("Job discovery progress")
        for name, label in labels.items():
            state = progress.get(name, {"status": "queued", "detail": ""})
            st.write(f"{icons.get(state['status'], '?')} **{label}:** {state['status'].title()}")
            if state.get("detail"):
                st.caption(state["detail"])


def _set_job_status(item: dict[str, object], status: str) -> None:
    try:
        with SessionLocal() as session:
            update_job_status(session, st.session_state.user.id, int(item["id"]), status)
        item["status"] = status
        st.rerun()
    except Exception as exc:
        st.error(f"Could not update job status: {exc}")


if st.session_state.user is None:
    show_auth_screen()
else:
    find_tab, tailor_tab = st.tabs(["Find Jobs", "Tailor Resume"])
    with find_tab:
        _render_find_jobs_tab()
    with tailor_tab:
        show_main_app()
