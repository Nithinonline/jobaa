from __future__ import annotations

from sqlalchemy import inspect, text

from db.models import Base, JobDescription, ResumeVersion, Settings
from db.session import SessionLocal, engine


def _add_column_if_missing(table_name: str, column_name: str, ddl: str) -> None:
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    if table_name not in tables:
        return
    if column_name in [col["name"] for col in inspector.get_columns(table_name)]:
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {ddl}"))


def run_migration() -> None:
    Base.metadata.create_all(bind=engine)

    _add_column_if_missing("job_descriptions", "content_hash", "content_hash VARCHAR(64)")
    _add_column_if_missing("job_descriptions", "source_url", "source_url VARCHAR(2000)")
    _add_column_if_missing("resume_versions", "match_score", "match_score FLOAT")
    _add_column_if_missing("resume_versions", "ats_score", "ats_score FLOAT")
    _add_column_if_missing("resume_versions", "tailored_document_bytes", "tailored_document_bytes BLOB")
    _add_column_if_missing("resume_versions", "tailored_format", "tailored_format VARCHAR(20) DEFAULT 'pdf'")
    _add_column_if_missing("resume_versions", "page_count", "page_count INTEGER DEFAULT 1")
    _add_column_if_missing("resume_versions", "layout_diff_json", "layout_diff_json TEXT")

    _add_column_if_missing("tailoring_sessions", "match_score", "match_score FLOAT")
    _add_column_if_missing("tailoring_sessions", "agent_progress_json", "agent_progress_json TEXT")
    _add_column_if_missing(
        "tailoring_sessions", "generated_resume_markdown", "generated_resume_markdown TEXT"
    )

    _add_column_if_missing("profiles", "master_resume_raw_text", "master_resume_raw_text TEXT")
    _add_column_if_missing("profiles", "master_resume_filename", "master_resume_filename VARCHAR(300)")
    _add_column_if_missing("profiles", "master_resume_mime_type", "master_resume_mime_type VARCHAR(100)")
    _add_column_if_missing("profiles", "master_resume_bytes", "master_resume_bytes BLOB")
    _add_column_if_missing("profiles", "master_page_count", "master_page_count INTEGER DEFAULT 1")
    _add_column_if_missing("profiles", "layout_profile_json", "layout_profile_json TEXT")
    _add_column_if_missing("profiles", "structured_profile_json", "structured_profile_json TEXT")
    _add_column_if_missing("profiles", "template_config_json", "template_config_json TEXT")
    _add_column_if_missing("profiles", "profile_source", "profile_source VARCHAR(50)")

    with SessionLocal() as session:
        for version in session.query(ResumeVersion).all():
            if version.match_score is not None and not isinstance(version.match_score, (int, float)):
                try:
                    version.match_score = float(version.match_score)
                except (TypeError, ValueError):
                    version.match_score = None
            if version.ats_score is not None and not isinstance(version.ats_score, (int, float)):
                try:
                    version.ats_score = float(version.ats_score)
                except (TypeError, ValueError):
                    version.ats_score = None

        for job_description in session.query(JobDescription).all():
            if not job_description.content_hash:
                job_description.content_hash = ""

        for setting in session.query(Settings).all():
            if setting.provider is None:
                setting.provider = "groq"

        session.commit()


if __name__ == "__main__":
    run_migration()
