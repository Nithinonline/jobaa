from __future__ import annotations

import os
from pathlib import Path

import streamlit as st
import streamlit_authenticator as stauth
from sqlalchemy.orm import Session

from db.models import User
from db.session import SessionLocal


def hash_password(password: str) -> str:
    return stauth.Hasher().hash(password)


def get_session() -> Session:
    return SessionLocal()


def ensure_user_exists(username: str, email: str, password: str) -> User:
    session = get_session()
    try:
        existing = session.query(User).filter((User.username == username) | (User.email == email)).first()
        if existing:
            raise ValueError("A user with that username or email already exists.")
        user = User(username=username, email=email, password_hash=hash_password(password))
        session.add(user)
        session.commit()
        session.refresh(user)
        return user
    finally:
        session.close()


def authenticate_user(username: str, password: str) -> User | None:
    session = get_session()
    try:
        user = session.query(User).filter(User.username == username).first()
        if not user:
            return None
        if stauth.Hasher().check_pw(password, user.password_hash):
            return user
        return None
    finally:
        session.close()


def logout() -> None:
    if "user" in st.session_state:
        del st.session_state["user"]
