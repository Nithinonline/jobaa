from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base

DB_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.environ.get("JOBAA_DB_PATH", str(DB_DIR / "joba.db"))
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    from db.migrate import run_migration

    run_migration()
