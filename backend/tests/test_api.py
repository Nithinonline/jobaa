from __future__ import annotations

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth.auth_config as auth_config
import api.main as api_main
from api.main import _issue_token, app, get_db
from core.profile_schema import ProfileData
from db.models import Base, JobListing, Profile, ResumeVersion, TailoringSession, User


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_sessions = sessionmaker(autoflush=False, bind=engine)

    def override_get_db():
        with test_sessions() as session:
            yield session

    monkeypatch.setattr(api_main, "init_db", lambda: None)
    monkeypatch.setattr(api_main, "SessionLocal", test_sessions)
    monkeypatch.setattr(auth_config, "get_session", lambda: test_sessions())
    app.dependency_overrides[get_db] = override_get_db
    with test_sessions() as session:
        session.add_all(
            [
                User(id=1, username="ada", email="ada@example.com", password_hash="hash"),
                User(id=2, username="grace", email="grace@example.com", password_hash="hash"),
            ]
        )
        session.flush()
        session.add(
            Profile(
                user_id=1,
                full_name="Ada Lovelace",
                structured_profile_json=ProfileData(
                    contact={"name": "Ada Lovelace"},
                    skills=["Python"],
                ).model_dump_json(),
            )
        )
        session.add(
            ResumeVersion(
                id=1,
                user_id=2,
                markdown_content="# Grace's private resume",
                created_at=datetime(2026, 1, 1),
            )
        )
        session.add(
            JobListing(
                user_id=2,
                url_hash="f" * 64,
                url="https://jobs.example.com/private",
                title="Private role",
                company="Example",
                posted_at=datetime(2026, 1, 1),
                source="test",
                jd_text="Private description",
            )
        )
        session.commit()

    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.mark.parametrize("identifier", ["ada", "ada@example.com", "ADA@EXAMPLE.COM"])
def test_login_accepts_username_or_email(client: TestClient, identifier: str) -> None:
    with auth_config.get_session() as session:
        user = session.query(User).filter(User.id == 1).one()
        user.password_hash = auth_config.hash_password("test-password")
        session.commit()

    response = client.post(
        "/api/auth/login",
        json={"username": identifier, "password": "test-password"},
    )

    assert response.status_code == 200
    assert response.json()["user"]["username"] == "ada"


def authorization(user_id: int = 1) -> dict[str, str]:
    user = User(id=user_id, username="test", email="test@example.com", password_hash="hash")
    return {"Authorization": f"Bearer {_issue_token(user)}"}


def test_user_routes_require_authentication(client: TestClient) -> None:
    response = client.get("/api/profile")

    assert response.status_code == 401


def test_logout_revokes_the_current_bearer_token(client: TestClient) -> None:
    headers = authorization()

    response = client.post("/api/auth/logout", headers=headers)
    current_user = client.get("/api/auth/me", headers=headers)

    assert response.status_code == 204
    assert current_user.status_code == 401


def test_profile_and_dashboard_are_scoped_to_authenticated_user(client: TestClient) -> None:
    profile = client.get("/api/profile", headers=authorization())
    dashboard = client.get("/api/dashboard", headers=authorization())

    assert profile.status_code == 200
    assert profile.json()["profile"]["contact"]["name"] == "Ada Lovelace"
    assert dashboard.status_code == 200
    assert dashboard.json()["user"]["username"] == "ada"
    assert dashboard.json()["stats"]["profile_ready"] is True


def test_user_cannot_download_another_users_resume(client: TestClient) -> None:
    response = client.get(
        "/api/resumes/1/download?format=md",
        headers=authorization(),
    )

    assert response.status_code == 404


def test_user_cannot_change_another_users_job_status(client: TestClient) -> None:
    response = client.patch(
        "/api/jobs/1",
        headers=authorization(),
        json={"status": "saved"},
    )

    assert response.status_code == 404


def test_invalid_job_status_is_rejected_before_mutation(client: TestClient) -> None:
    response = client.patch(
        "/api/jobs/1",
        headers=authorization(),
        json={"status": "archived"},
    )

    assert response.status_code == 422


def test_tailor_endpoint_runs_workflow_and_streams_completion(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.application_crew as application_crew
    import core.services.tailoring_service as tailoring_service
    from core.application_crew import (
        CandidateProfileOutput,
        JobResearchOutput,
        ResumeStrategyOutput,
    )
    from core.retriever import RetrievalBundle

    def run_agent_task(**kwargs):
        output_model = kwargs["output_model"]
        if output_model is JobResearchOutput:
            return JobResearchOutput(
                title="Backend Engineer",
                required_skills=["Python"],
                responsibilities=["Build APIs"],
            )
        if output_model is CandidateProfileOutput:
            return CandidateProfileOutput(relevant_skills=["Python"])
        if output_model is ResumeStrategyOutput:
            return ResumeStrategyOutput(skills=["Python"])
        raise AssertionError(f"Unexpected agent output model: {output_model}")

    monkeypatch.setattr(application_crew, "_create_llm", lambda: object())
    monkeypatch.setattr(application_crew, "_run_agent_task", run_agent_task)
    monkeypatch.setattr(
        tailoring_service,
        "retrieve_evidence",
        lambda *args, **kwargs: RetrievalBundle(),
    )

    response = client.post(
        "/api/tailor",
        headers=authorization(),
        data={
            "jd_text": "Backend engineer needed to build APIs with Python.",
            "jd_title": "Backend Engineer",
        },
    )

    assert response.status_code == 200
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    completion = next(event for event in events if event["type"] == "complete")
    assert "Python" in completion["data"]["markdown_content"]
    assert completion["data"]["agent_progress"]["job_research"]["status"] == "completed"
    assert completion["data"]["agent_progress"]["candidate_profiling"]["status"] == "completed"
    assert completion["data"]["agent_progress"]["resume_strategy"]["status"] == "completed"
    with api_main.SessionLocal() as session:
        assert session.query(ResumeVersion).filter_by(user_id=1).count() == 1
        assert session.query(TailoringSession).filter_by(user_id=1).one().status == "complete"


def test_tailor_endpoint_streams_agent_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.application_crew as application_crew
    import core.services.tailoring_service as tailoring_service
    from core.retriever import RetrievalBundle

    def fail_agent_task(**kwargs):
        raise RuntimeError("structured output provider failed")

    monkeypatch.setattr(application_crew, "_create_llm", lambda: object())
    monkeypatch.setattr(application_crew, "_run_agent_task", fail_agent_task)
    monkeypatch.setattr(
        tailoring_service,
        "retrieve_evidence",
        lambda *args, **kwargs: RetrievalBundle(),
    )

    response = client.post(
        "/api/tailor",
        headers=authorization(),
        data={"jd_text": "Backend engineer needed to build APIs with Python."},
    )

    assert response.status_code == 200
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    failure = next(event for event in events if event["type"] == "error")
    assert "structured output provider failed" in failure["message"]
    progress = [
        event["data"]
        for event in events
        if event["type"] == "progress"
    ]
    assert progress[-1]["job_research"]["status"] == "failed"
    assert progress[-1]["candidate_profiling"]["status"] == "failed"
    with api_main.SessionLocal() as session:
        assert session.query(TailoringSession).filter_by(user_id=1).one().status == "failed"
