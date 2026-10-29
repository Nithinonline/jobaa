from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models import Base, JobListing, User


def _listing(user_id: int, url_hash: str = "a" * 64) -> JobListing:
    return JobListing(
        user_id=user_id,
        url_hash=url_hash,
        url="https://jobs.example.com/role",
        title="Backend Engineer",
        company="Example Co",
        location="Remote",
        remote=True,
        posted_at=datetime(2026, 10, 1),
        source="test",
        jd_text="Python backend role",
    )


def test_job_listing_table_is_created_and_defaults_to_new() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    assert "job_listings" in inspect(engine).get_table_names()
    with Session(engine) as session:
        user = User(username="ada", email="ada@example.com", password_hash="hash")
        session.add(user)
        session.flush()
        listing = _listing(user.id)
        session.add(listing)
        session.commit()
        session.refresh(listing)

        assert listing.status == "new"
        assert listing.created_at is not None


def test_job_listing_url_hash_is_unique_per_user() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        users = [
            User(username="ada", email="ada@example.com", password_hash="hash"),
            User(username="grace", email="grace@example.com", password_hash="hash"),
        ]
        session.add_all(users)
        session.flush()
        session.add_all([_listing(users[0].id), _listing(users[1].id)])
        session.commit()

        session.add(_listing(users[0].id))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_job_listing_rejects_unknown_status() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user = User(username="ada", email="ada@example.com", password_hash="hash")
        session.add(user)
        session.flush()
        listing = _listing(user.id)
        listing.status = "archived"
        session.add(listing)

        with pytest.raises(IntegrityError):
            session.commit()
