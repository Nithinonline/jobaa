"""Application workflow orchestration, persistence, and resume scoring."""

from __future__ import annotations

import json
import logging
from typing import Callable

from sqlalchemy.orm import Session

from core.application_crew import run_application_crew
from core.ats_scorer import score_resume
from core.cache import get_or_create_job_description
from core.jd_parser import get_priority_keywords, parsed_to_db_fields
from core.layout_schema import LayoutBudget, MasterLayoutProfile
from core.matcher import compute_match_result
from core.profile_schema import ProfileData
from core.retriever import retrieve_evidence
from core.services.profile_service import get_layout_profile, get_template_config
from core.spatial_validator import SpatialValidator, count_pdf_pages
from core.template_config import TemplateConfig
from db.models import JobDescription, Profile, ResumeVersion, TailoringSession

AgentProgress = dict[str, dict[str, str]]
ProgressCallback = Callable[[AgentProgress], None]
logger = logging.getLogger(__name__)


def _initial_progress() -> AgentProgress:
    return {
        "job_research": {"status": "queued", "detail": ""},
        "candidate_profiling": {"status": "queued", "detail": ""},
        "resume_strategy": {"status": "queued", "detail": ""},
    }


def run_tailoring_workflow(
    session: Session,
    *,
    user_id: int,
    profile: Profile,
    profile_data: ProfileData,
    jd_text: str,
    jd_title: str = "Untitled role",
    jd_source_url: str | None = None,
    template_config: TemplateConfig | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, object]:
    """Run the CrewAI workflow with spatial budgeting and persist tailored document bytes."""
    jd = get_or_create_job_description(
        session,
        user_id,
        jd_text,
        jd_title or "Untitled role",
        source_url=jd_source_url,
    )
    progress = _initial_progress()
    row = TailoringSession(
        user_id=user_id,
        job_description_id=jd.id,
        status="running",
        agent_progress_json=json.dumps(progress),
    )
    session.add(row)
    session.commit()
    session.refresh(row)

    def save_progress(updated: AgentProgress) -> None:
        nonlocal progress
        progress = updated
        row.agent_progress_json = json.dumps(progress)
        session.commit()
        if progress_callback is not None:
            progress_callback({name: value.copy() for name, value in progress.items()})

    if progress_callback is not None:
        progress_callback({name: value.copy() for name, value in progress.items()})

    try:
        progress["candidate_profiling"] = {
            "status": "running",
            "detail": "Retrieving matching master-resume evidence",
        }
        save_progress(progress)
        evidence = retrieve_evidence(user_id, profile_data, jd_text, jd=jd)

        # Retrieve layout profile and budget from master resume
        layout_profile = get_layout_profile(profile)
        layout_budget = layout_profile.derive_layout_budget()
        effective_template_config = (
            layout_profile.to_template_config()
            if profile.layout_profile_json
            else (template_config or get_template_config(profile))
        )
        target_pages = max(1, profile.master_page_count or 1)

        workflow = run_application_crew(
            jd_text=jd_text,
            profile=profile_data,
            evidence=evidence,
            template_config=effective_template_config,
            progress_callback=save_progress,
            initial_progress=progress,
            layout_budget=layout_budget,
        )
        research = workflow.job_research

        jd.title = research.title or jd.title or jd_title
        for field, value in parsed_to_db_fields(research).items():
            setattr(jd, field, value)

        match_result = compute_match_result(profile_data, jd_text, jd=jd)
        ats_score, improvement_summary, missing_keywords = score_resume(
            workflow.markdown_content,
            jd_text,
            jd=jd,
        )
        priority_keywords = get_priority_keywords(jd)

        # Enforce strict 1-page fit and render tailored PDF in master template
        from core.pdf_exporter import generate_pdf_bytes

        def render_pdf_pass(params: dict) -> bytes | None:
            cfg = effective_template_config.model_copy()
            if "margin_squeeze_offset" in params:
                cfg.margin_inches = max(0.3, cfg.margin_inches + params["margin_squeeze_offset"])
                cfg.top_margin_inches = max(0.25, cfg.top_margin_inches + params["margin_squeeze_offset"])
                cfg.bottom_margin_inches = max(0.25, cfg.bottom_margin_inches + params["margin_squeeze_offset"])
            if "font_scale_offset" in params:
                cfg.body_font_size = max(8.0, cfg.body_font_size + params["font_scale_offset"])
                cfg.heading_font_size = max(10.0, cfg.heading_font_size + params["font_scale_offset"])
            if "section_gap_factor" in params:
                cfg.section_gap_inches = max(0.015, cfg.section_gap_inches * params["section_gap_factor"])
            return generate_pdf_bytes(
                workflow.markdown_content,
                profile=profile,
                expected_keywords=list(missing_keywords) if missing_keywords else None,
                job_title=jd.title,
                template_config=cfg,
            )

        pdf_bytes, final_pages, was_compacted = SpatialValidator.enforce_page_budget(
            render_fn=render_pdf_pass,
            target_page_count=target_pages,
        )

        version = ResumeVersion(
            user_id=user_id,
            job_description_id=jd.id,
            markdown_content=workflow.markdown_content,
            tailored_document_bytes=pdf_bytes,
            tailored_format="pdf",
            page_count=final_pages or 1,
            ats_score=ats_score,
            match_score=match_result.score,
            improvement_summary=improvement_summary,
            missing_keywords=", ".join(missing_keywords),
        )
        session.add(version)
        row.status = "complete"
        row.generated_resume_markdown = workflow.markdown_content
        row.match_score = match_result.score
        session.commit()
        session.refresh(version)
        session.refresh(row)
        return {
            "markdown_content": workflow.markdown_content,
            "ats_score": ats_score,
            "match_score": match_result.score,
            "match_components": match_result.components,
            "missing_keywords": missing_keywords,
            "improvements": improvement_summary,
            "priority_keywords": priority_keywords,
            "job_title": jd.title or jd_title or "Job",
            "profile_id": profile.id,
            "session_id": row.id,
            "version_id": version.id,
            "page_count": final_pages or 1,
            "master_page_count": target_pages,
            "template_preserved": True,
            "tailored_format": "pdf",
            "evidence_count": len(evidence.hits),
            "agent_progress": progress,
        }
    except Exception:
        for agent, state in progress.items():
            if state["status"] == "running":
                state["status"] = "failed"
                state["detail"] = state["detail"] or "Workflow failed before this stage completed."
        row.agent_progress_json = json.dumps(progress)
        row.status = "failed"
        session.commit()
        if progress_callback is not None:
            progress_callback({name: value.copy() for name, value in progress.items()})
        raise
