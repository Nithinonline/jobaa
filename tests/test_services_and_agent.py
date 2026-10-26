"""Tests for the current agent workflow and safe job-posting input."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.ats_constants import ContactInfo
from core.application_crew import (
    CandidateProfileOutput,
    CrewWorkflowOutput,
    EntrySelection,
    JobResearchOutput,
    ResumeStrategyOutput,
    _validate_candidate_profile,
    apply_resume_strategy,
    run_application_crew,
)
from core.file_parser import strip_html_to_text
from core.job_source import fetch_job_posting
from core.profile_schema import ExperienceEntry, ProfileData
from core.retriever import RetrievalBundle
from core.services.tailoring_service import run_tailoring_workflow
from core.template_config import TemplateConfig
from db.models import Base, Profile, ResumeVersion, TailoringSession, User


def _profile() -> ProfileData:
    return ProfileData(
        contact=ContactInfo(name="Ada", email="ada@example.com"),
        summary="Software engineer focused on Python services.",
        skills=["Python", "SQL"],
        experience=[
            ExperienceEntry(
                id="exp-1",
                title="Engineer",
                company="Acme",
                start_date="January 2022",
                end_date="Present",
                bullets=["Built APIs with Python"],
            )
        ],
        education=[
            ExperienceEntry(
                id="edu-1",
                title="B.S. Computer Science",
                company="State University",
                start_date="May 2018",
                end_date="May 2018",
            )
        ],
    )


def test_candidate_profile_rejects_skills_not_in_master_profile() -> None:
    with pytest.raises(ValueError, match="absent from the master profile"):
        _validate_candidate_profile(
            _profile(),
            CandidateProfileOutput(relevant_skills=["Kubernetes"]),
        )


def test_resume_strategy_selects_only_verified_facts() -> None:
    profile = _profile()
    candidate = CandidateProfileOutput(
        relevant_skills=["Python"],
        experience_indices=[0],
    )
    selected = apply_resume_strategy(
        profile,
        candidate,
        ResumeStrategyOutput(
            skills=["Python"],
            experience=[EntrySelection(source_index=0, bullet_indices=[0])],
        ),
    )
    assert selected.skills == ["Python"]
    assert selected.experience[0].bullets == ["Built APIs with Python"]


def test_resume_strategy_rejects_unverified_source_indices() -> None:
    with pytest.raises(ValueError, match="not identified as relevant"):
        apply_resume_strategy(
            _profile(),
            CandidateProfileOutput(),
            ResumeStrategyOutput(
                experience=[EntrySelection(source_index=0, bullet_indices=[0])]
            ),
        )


def test_application_crew_runs_all_agents_and_reports_progress(monkeypatch) -> None:
    def run_agent_task(**kwargs):
        model = kwargs["output_model"]
        if model is JobResearchOutput:
            return JobResearchOutput(
                title="Backend Engineer",
                required_skills=["Python"],
                responsibilities=["Build APIs"],
            )
        if model is CandidateProfileOutput:
            return CandidateProfileOutput(
                relevant_skills=["Python"],
                experience_indices=[0],
            )
        if model is ResumeStrategyOutput:
            return ResumeStrategyOutput(
                skills=["Python"],
                experience=[EntrySelection(source_index=0, bullet_indices=[0])],
            )
        raise AssertionError(f"Unexpected agent output model: {model}")

    monkeypatch.setattr("core.application_crew._create_llm", lambda: object())
    monkeypatch.setattr("core.application_crew._run_agent_task", run_agent_task)
    progress_updates: list[dict[str, dict[str, str]]] = []
    result = run_application_crew(
        jd_text="Backend Engineer needed. Python and API experience required.",
        profile=_profile(),
        evidence=RetrievalBundle(),
        template_config=TemplateConfig(),
        progress_callback=progress_updates.append,
    )

    assert result.job_research.title == "Backend Engineer"
    assert "Built APIs with Python" in result.markdown_content
    assert progress_updates[-1]["job_research"]["status"] == "completed"
    assert progress_updates[-1]["candidate_profiling"]["status"] == "completed"
    assert progress_updates[-1]["resume_strategy"]["status"] == "completed"


def test_fetch_job_posting_extracts_text_from_public_html(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.job_source.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))],
    )
    response = MagicMock()
    response.is_redirect = False
    response.headers = {"Content-Type": "text/html; charset=utf-8"}
    response.encoding = "utf-8"
    response.iter_content.return_value = [
        b"<html><body><h1>Backend Engineer</h1><p>"
        b"Build reliable services with Python and SQL. "
        b"Work with a distributed engineering team.</p>"
        b"<script>ignore this</script></body></html>"
    ]
    response.raise_for_status.return_value = None
    monkeypatch.setattr("core.job_source.requests.get", lambda *args, **kwargs: response)

    text = fetch_job_posting("https://jobs.example/role")

    assert "Backend Engineer" in text
    assert "Python and SQL" in text
    assert "ignore this" not in text
    response.close.assert_called_once()


def test_fetch_job_posting_rejects_private_addresses(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.job_source.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 443))],
    )
    request = MagicMock()
    monkeypatch.setattr("core.job_source.requests.get", request)

    with pytest.raises(ValueError, match="Private or reserved"):
        fetch_job_posting("https://localhost/role")
    request.assert_not_called()


def test_strip_html_removes_markup_and_scripts() -> None:
    raw = "<div><h2>Engineer</h2><p>Need <b>Python</b> and SQL.</p><script>x()</script></div>"
    text = strip_html_to_text(raw)
    assert "Python" in text
    assert "SQL" in text
    assert "<script>" not in text
    assert "x()" not in text


def test_tailoring_service_persists_progress_and_resume(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(username="ada", email="ada@example.com", password_hash="hash")
        session.add(user)
        session.flush()
        profile_row = Profile(user_id=user.id)
        session.add(profile_row)
        session.flush()

        research = JobResearchOutput(
            title="Backend Engineer",
            required_skills=["Python"],
            responsibilities=["Build APIs"],
        )
        workflow_output = CrewWorkflowOutput(
            markdown_content="## Skills\n- Technical : Python\n",
            job_research=research,
            candidate_profile=CandidateProfileOutput(
                relevant_skills=["Python"],
                experience_indices=[0],
            ),
            resume_strategy=ResumeStrategyOutput(
                skills=["Python"],
                experience=[EntrySelection(source_index=0, bullet_indices=[0])],
            ),
        )

        monkeypatch.setattr(
            "core.services.tailoring_service.retrieve_evidence",
            lambda *args, **kwargs: RetrievalBundle(),
        )

        def run_crew(**kwargs):
            progress = kwargs["initial_progress"]
            for agent in progress:
                progress[agent] = {"status": "completed", "detail": ""}
            kwargs["progress_callback"](progress)
            return workflow_output

        monkeypatch.setattr("core.services.tailoring_service.run_application_crew", run_crew)
        monkeypatch.setattr(
            "core.services.tailoring_service.compute_match_result",
            lambda *args, **kwargs: MagicMock(score=82.0, components={"skills": 82.0}),
        )
        monkeypatch.setattr(
            "core.services.tailoring_service.score_resume",
            lambda *args, **kwargs: (91.0, "Good keyword coverage.", ["SQL"]),
        )
        monkeypatch.setattr(
            "core.services.tailoring_service.get_priority_keywords",
            lambda *args, **kwargs: ["Python"],
        )
        progress_updates: list[dict[str, dict[str, str]]] = []

        result = run_tailoring_workflow(
            session,
            user_id=user.id,
            profile=profile_row,
            profile_data=_profile(),
            jd_text="Backend Engineer. Python experience required.",
            jd_source_url="https://jobs.example/role",
            progress_callback=progress_updates.append,
        )

        saved_task = session.get(TailoringSession, result["session_id"])
        saved_version = session.get(ResumeVersion, result["version_id"])
        assert result["job_title"] == "Backend Engineer"
        assert saved_task is not None and saved_task.status == "complete"
        assert saved_task.generated_resume_markdown == workflow_output.markdown_content
        assert saved_version is not None and saved_version.ats_score == 91.0
        assert saved_task.agent_progress_json is not None
        assert '"status": "completed"' in saved_task.agent_progress_json
        saved_jd = saved_task.job_description
        assert saved_jd is not None and saved_jd.source_url == "https://jobs.example/role"
        assert progress_updates[0]["job_research"]["status"] == "queued"
