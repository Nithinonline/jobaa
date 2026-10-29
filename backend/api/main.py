from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Annotated, Any, Iterator, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from auth.auth_config import authenticate_user, ensure_user_exists
from core.pdf_editor import edit_master_pdf
from api.models import RevokedApiToken
from core.file_parser import parse_uploaded_file
from core.job_source import fetch_job_posting
from core.layout_analyzer import analyze_master_layout
from core.profile_schema import ProfileData
from core.resume_parser import parse_master_resume
from core.services.export_service import export_docx, export_pdf, resume_filename
from core.services.profile_service import (
    get_layout_profile,
    get_or_create_profile,
    get_template_config,
    load_profile_data,
    save_master_profile,
)
from db.models import JobListing, Profile, ResumeVersion, User
from db.session import SessionLocal, init_db

logger = logging.getLogger(__name__)
_TOKEN_MAX_AGE = 60 * 60 * 12
_serializer = URLSafeTimedSerializer(
    os.environ.get("JOBAA_API_SECRET_KEY") or secrets.token_urlsafe(32),
    salt="jobaa-api-session",
)
_bearer = HTTPBearer(auto_error=False)


class SignupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=8, max_length=256)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        username = value.strip()
        if len(username) < 3:
            raise ValueError("Username must contain at least three non-space characters.")
        return username

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or "." not in email.rsplit("@", 1)[-1] or any(char.isspace() for char in email):
            raise ValueError("Enter a valid email address.")
        return email


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=256)


class JobSearchRequest(BaseModel):
    location: str = Field(default="", max_length=200)
    remote_only: bool = False
    max_age_days: int = Field(default=30, ge=1, le=365)
    top_n: int = Field(default=10, ge=1, le=20)


class JobStatusRequest(BaseModel):
    status: Literal["new", "saved", "applied", "ignored"]


class UserView(BaseModel):
    id: int
    username: str
    email: str


class ProfileSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: ProfileData


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Joba API", version="1.0.0", lifespan=lifespan)
allowed_origins = [
    origin.strip()
    for origin in os.environ.get(
        "JOBAA_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


DbSession = Annotated[Session, Depends(get_db)]


def _user_view(user: User) -> dict[str, Any]:
    return {"id": user.id, "username": user.username, "email": user.email}


def _current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ],
    session: DbSession,
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    try:
        payload = _serializer.loads(credentials.credentials, max_age=_TOKEN_MAX_AGE)
        user_id = int(payload["user_id"])
        token_id = payload["jti"]
        if not isinstance(token_id, str):
            raise ValueError("Invalid token ID.")
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Your session has expired. Sign in again.")
    revoked = session.get(RevokedApiToken, token_id)
    if revoked is not None and revoked.expires_at > datetime.now(timezone.utc).replace(tzinfo=None):
        raise HTTPException(status_code=401, detail="Your session has ended. Sign in again.")
    user = session.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
    if user is None:
        raise HTTPException(status_code=401, detail="This account is unavailable.")
    return user


CurrentUser = Annotated[User, Depends(_current_user)]


def _issue_token(user: User) -> str:
    return _serializer.dumps({"user_id": user.id, "jti": secrets.token_urlsafe(18)})


def _profile_view(profile: Profile | None) -> dict[str, Any]:
    data = load_profile_data(profile) if profile else None
    layout = get_layout_profile(profile) if profile and profile.layout_profile_json else None
    return {
        "profile": (data or ProfileData()).model_dump(mode="json"),
        "has_profile": data is not None,
        "source": profile.profile_source if profile else None,
        "filename": profile.master_resume_filename if profile else None,
        "master_page_count": getattr(profile, "master_page_count", 1) or 1,
        "layout_profile": layout.model_dump(mode="json") if layout else None,
        "updated_at": profile.updated_at.isoformat() if profile and profile.updated_at else None,
    }


def _job_view(listing: JobListing) -> dict[str, Any]:
    return {
        "id": listing.id,
        "url": listing.url,
        "title": listing.title,
        "company": listing.company,
        "location": listing.location,
        "remote": listing.remote,
        "posted_at": listing.posted_at.isoformat(),
        "source": listing.source,
        "jd_text": listing.jd_text,
        "match_score": listing.match_score,
        "fit_note": listing.fit_note,
        "status": listing.status,
        "created_at": listing.created_at.isoformat() if listing.created_at else None,
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/signup")
def signup(payload: SignupRequest, session: DbSession) -> dict[str, Any]:
    existing = (
        session.query(User)
        .filter((User.username == payload.username) | (User.email == payload.email))
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="A user with that username or email already exists.")
    user = ensure_user_exists(session, payload.username, payload.password, email=payload.email)
    get_or_create_profile(session, user.id)
    token = _issue_token(user)
    return {"token": token, "user": _user_view(user)}


@app.post("/api/auth/login")
def login(payload: LoginRequest, session: DbSession) -> dict[str, Any]:
    user = authenticate_user(payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    token = _issue_token(user)
    return {"token": token, "user": _user_view(user)}


@app.get("/api/auth/me")
def me(user: CurrentUser) -> dict[str, Any]:
    return {"user": _user_view(user)}


@app.post("/api/auth/logout")
def logout(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ],
    session: DbSession,
    user: CurrentUser,
) -> Response:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    try:
        payload = _serializer.loads(credentials.credentials, max_age=_TOKEN_MAX_AGE)
        token_id = payload["jti"]
        if not isinstance(token_id, str):
            raise ValueError("Invalid token ID.")
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Your session has expired. Sign in again.")
    if session.get(RevokedApiToken, token_id) is None:
        session.add(
            RevokedApiToken(
                token_id=token_id,
                expires_at=(
                    datetime.now(timezone.utc).replace(tzinfo=None)
                    + timedelta(seconds=_TOKEN_MAX_AGE)
                ),
            )
        )
        session.commit()
    logger.info("API session logged out for user_id=%s", user.id)
    return Response(status_code=204)


@app.get("/api/dashboard")
def dashboard(user: CurrentUser, session: DbSession) -> dict[str, Any]:
    profile = session.query(Profile).filter(Profile.user_id == user.id).first()
    profile_data = load_profile_data(profile) if profile else None
    versions = (
        session.query(ResumeVersion)
        .filter(ResumeVersion.user_id == user.id)
        .order_by(ResumeVersion.created_at.desc())
        .limit(5)
        .all()
    )
    from core.services.job_discovery_service import list_job_listings

    jobs = list_job_listings(session, user.id)
    return {
        "user": _user_view(user),
        "profile": _profile_view(profile),
        "stats": {
            "resume_count": session.query(ResumeVersion)
            .filter(ResumeVersion.user_id == user.id)
            .count(),
            "saved_jobs": sum(job.status == "saved" for job in jobs),
            "applied_jobs": sum(job.status == "applied" for job in jobs),
            "profile_ready": bool(profile_data and (profile_data.skills or profile_data.experience)),
        },
        "recent_resumes": [_resume_view(version) for version in versions],
        "recent_jobs": [_job_view(job) for job in jobs[:5]],
    }


def _resume_view(version: ResumeVersion) -> dict[str, Any]:
    jd = version.job_description
    return {
        "id": version.id,
        "title": jd.title if jd and jd.title else version.version_name or "Tailored resume",
        "company": None,
        "match_score": version.match_score,
        "ats_score": version.ats_score,
        "page_count": getattr(version, "page_count", 1) or 1,
        "tailored_format": getattr(version, "tailored_format", "pdf") or "pdf",
        "has_tailored_document": bool(getattr(version, "tailored_document_bytes", None)),
        "improvement_summary": version.improvement_summary,
        "missing_keywords": version.missing_keywords,
        "created_at": version.created_at.isoformat() if version.created_at else None,
    }


@app.get("/api/profile")
def get_profile(user: CurrentUser, session: DbSession) -> dict[str, Any]:
    profile = session.query(Profile).filter(Profile.user_id == user.id).first()
    return _profile_view(profile)


@app.put("/api/profile")
def put_profile(payload: ProfileSaveRequest, user: CurrentUser, session: DbSession) -> dict[str, Any]:
    profile = get_or_create_profile(session, user.id)
    save_master_profile(session, profile, payload.profile, source="manual")
    return _profile_view(profile)


@app.post("/api/profile/import")
async def import_profile(
    user: CurrentUser,
    session: DbSession,
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    filename = file.filename or ""
    if not filename.lower().endswith((".pdf", ".docx", ".txt")):
        raise HTTPException(status_code=415, detail="Upload a PDF, DOCX, or TXT resume.")
    contents = await file.read(10 * 1024 * 1024 + 1)
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Resume files must be 10 MB or smaller.")
    try:
        source = BytesIO(contents)
        source.name = filename
        raw_text = parse_uploaded_file(source)
        data = parse_master_resume(raw_text)
        layout_profile = analyze_master_layout(contents, filename, raw_text=raw_text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Master resume import failed for user_id=%s", user.id)
        raise HTTPException(status_code=422, detail="The resume could not be parsed.") from exc
    profile = get_or_create_profile(session, user.id)
    save_master_profile(
        session,
        profile,
        data,
        source="upload",
        raw_text=raw_text,
        filename=filename,
        raw_bytes=contents,
        mime_type=file.content_type or ("application/pdf" if filename.lower().endswith(".pdf") else "application/octet-stream"),
        layout_profile=layout_profile,
    )
    return _profile_view(profile)


@app.post("/api/tailor")
async def tailor(
    user: CurrentUser,
    jd_text: Annotated[str, Form()] = "",
    jd_title: Annotated[str, Form()] = "Untitled role",
    jd_url: Annotated[str, Form()] = "",
    file: Annotated[UploadFile | None, File()] = None,
) -> StreamingResponse:
    source_text = jd_text.strip()
    if file is not None:
        if not (file.filename or "").lower().endswith((".pdf", ".docx", ".txt")):
            raise HTTPException(status_code=415, detail="Use a PDF, DOCX, or TXT job description.")
        contents = await file.read(10 * 1024 * 1024 + 1)
        if len(contents) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Job description files must be 10 MB or smaller.")
        try:
            source = BytesIO(contents)
            source.name = file.filename or "job-description.txt"
            source_text = parse_uploaded_file(source)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    elif jd_url.strip():
        try:
            source_text = fetch_job_posting(jd_url.strip())
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Could not read that job posting: {exc}") from exc
    if not source_text or len(source_text) > 50000:
        raise HTTPException(status_code=422, detail="Provide a job description of 1–50,000 characters.")

    loop = asyncio.get_running_loop()
    events: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    def publish(kind: str, data: Any) -> None:
        loop.call_soon_threadsafe(events.put_nowait, (kind, data))

    def run() -> dict[str, object]:
        try:
            with SessionLocal() as session:
                profile = session.query(Profile).filter(Profile.user_id == user.id).first()
                profile_data = load_profile_data(profile) if profile else None
                if profile is None or profile_data is None:
                    raise ValueError("Save your master resume before tailoring.")
                from core.services.tailoring_service import run_tailoring_workflow

                return run_tailoring_workflow(
                    session,
                    user_id=user.id,
                    profile=profile,
                    profile_data=profile_data,
                    jd_text=source_text,
                    jd_title=jd_title.strip() or "Untitled role",
                    jd_source_url=jd_url.strip() or None,
                    template_config=get_template_config(profile),
                    progress_callback=lambda progress: publish("progress", progress),
                )
        except Exception as exc:
            logger.exception("Tailoring failed for user_id=%s", user.id)
            raise exc

    async def stream() -> Any:
        task = asyncio.create_task(asyncio.to_thread(run))
        yield f"data: {json.dumps({'type': 'started'})}\n\n"
        while not task.done():
            try:
                kind, data = await asyncio.wait_for(events.get(), timeout=15)
                yield f"data: {json.dumps({'type': kind, 'data': data}, default=str)}\n\n"
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
        while not events.empty():
            kind, data = events.get_nowait()
            yield f"data: {json.dumps({'type': kind, 'data': data}, default=str)}\n\n"
        try:
            result = task.result()
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'complete', 'data': result}, default=str)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/resumes")
def list_resumes(user: CurrentUser, session: DbSession) -> list[dict[str, Any]]:
    rows = (
        session.query(ResumeVersion)
        .filter(ResumeVersion.user_id == user.id)
        .order_by(ResumeVersion.created_at.desc())
        .limit(100)
        .all()
    )
    return [_resume_view(row) for row in rows]


@app.get("/api/resumes/{resume_id}/download")
def download_resume(
    resume_id: int,
    format: Literal["md", "pdf", "docx"],
    user: CurrentUser,
    session: DbSession,
) -> Response:
    version = (
        session.query(ResumeVersion)
        .filter(ResumeVersion.id == resume_id, ResumeVersion.user_id == user.id)
        .first()
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Resume version not found.")
    content = version.markdown_content or ""
    job_title = version.job_description.title if version.job_description else "Resume"
    if format == "md":
        filename = os.path.splitext(resume_filename(
            session.query(Profile).filter(Profile.user_id == user.id).first(), job_title
        ))[0] + ".md"
        return Response(
            content,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    profile = _profile_for_export(session, user.id)
    if format == "pdf":
        if getattr(version, "tailored_document_bytes", None):
            document = version.tailored_document_bytes
            error = None
        else:
            document, _issues, error = export_pdf(content, profile, block_on_issues=True)
        media_type = "application/pdf"
    else:
        document, _issues, error = export_docx(content, profile, block_on_issues=True)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if error or document is None:
        raise HTTPException(status_code=422, detail=error or "Resume export could not be generated.")
    filename = os.path.splitext(resume_filename(profile, job_title))[0]
    ext = "pdf" if format == "pdf" else "docx"
    return Response(
        document,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}.{ext}"'},
    )


def _profile_for_export(session: Session, user_id: int) -> Profile:
    profile = session.query(Profile).filter(Profile.user_id == user_id).first()
    if profile is None:
        raise HTTPException(status_code=404, detail="Master resume not found.")
    return profile


@app.get("/api/jobs")
def get_jobs(
    user: CurrentUser, session: DbSession, status: str | None = None
) -> list[dict[str, Any]]:
    try:
        from core.services.job_discovery_service import list_job_listings

        return [_job_view(row) for row in list_job_listings(session, user.id, status)]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/jobs/search")
def search_jobs(payload: JobSearchRequest, user: CurrentUser) -> dict[str, Any]:
    try:
        from core.services.job_discovery_service import run_job_search

        return run_job_search(
            user.id,
            payload.location,
            payload.remote_only,
            payload.max_age_days,
            payload.top_n,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Job search failed for user_id=%s", user.id)
        raise HTTPException(status_code=502, detail="Job search could not be completed.") from exc


@app.patch("/api/jobs/{job_id}")
def patch_job(
    job_id: int,
    payload: JobStatusRequest,
    user: CurrentUser,
    session: DbSession,
) -> dict[str, str]:
    try:
        from core.services.job_discovery_service import update_job_status

        update_job_status(session, user.id, job_id, payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": payload.status}
