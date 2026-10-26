"""Application workflow orchestration, persistence, and resume scoring."""

from __future__ import annotations

import json
from typing import Callable

from sqlalchemy.orm import Session

from core.application_crew import run_application_crew
from core.ats_scorer import score_resume
from core.cache import get_or_create_job_description
from core.jd_parser import get_priority_keywords, parsed_to_db_fields
from core.matcher import compute_match_result
from core.profile_schema import ProfileData
from core.retriever import retrieve_evidence
from core.template_config import TemplateConfig
from db.models import JobDescription, Profile, ResumeVersion, TailoringSession

AgentProgress = dict[str, dict[str, str]]
ProgressCallback = Callable[[AgentProgress], None]


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
    """Run the new CrewAI workflow and persist its session and generated version."""
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
        workflow = run_application_crew(
            jd_text=jd_text,
            profile=profile_data,
            evidence=evidence,
            template_config=template_config or TemplateConfig(),
            progress_callback=save_progress,
            initial_progress=progress,
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
        version = ResumeVersion(
            user_id=user_id,
            job_description_id=jd.id,
            markdown_content=workflow.markdown_content,
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
