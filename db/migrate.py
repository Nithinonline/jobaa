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
    _add_column_if_missing("resume_versions", "match_score", "match_score FLOAT")
    _add_column_if_missing("resume_versions", "ats_score", "ats_score FLOAT")
    _add_column_if_missing("tailoring_sessions", "match_score", "match_score FLOAT")
    _add_column_if_missing("profiles", "master_resume_raw_text", "master_resume_raw_text TEXT")
    _add_column_if_missing("profiles", "master_resume_filename", "master_resume_filename VARCHAR(300)")
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
            if setting.match_threshold is None:
                setting.match_threshold = 70

        session.commit()


if __name__ == "__main__":
    run_migration()
