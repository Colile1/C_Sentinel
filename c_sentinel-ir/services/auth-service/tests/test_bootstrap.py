"""
test_bootstrap.py - the startup seeding of the one bootstrap admin.

`ensure_bootstrap_admin` closes the chicken-and-egg gap: a fresh auth_db has no
users, and `POST /auth/users` needs an admin token. These tests pin its three
behaviours - it creates the admin when configured, it is idempotent across
restarts, and it does nothing when unconfigured - against the real SQLite
schema, no container.

Author: Colile
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.repositories.user_repository import UserRepository  # noqa: E402
from app.schemas import Role  # noqa: E402
from app.services import bootstrap as bootstrap_module  # noqa: E402
from app.services.password_service import verify_password  # noqa: E402


@pytest.fixture
def wire_bootstrap(session_factory, monkeypatch):
    """
    Purpose: point `ensure_bootstrap_admin` at the test's SQLite session factory
             and let each test set the two settings values.
    Inputs:  the SQLite session factory and monkeypatch.
    Output:  a callable taking `username` and `password`, returning the session
             factory so the test can inspect what was written.
    """

    def _run(username: str, password: str):
        class _Settings:
            bootstrap_admin_username = username
            bootstrap_admin_password = password

        monkeypatch.setattr(bootstrap_module, "get_settings", lambda _name: _Settings())
        monkeypatch.setattr(bootstrap_module, "get_session_factory", lambda: session_factory)
        bootstrap_module.ensure_bootstrap_admin()
        return session_factory

    return _run


def test_creates_the_admin_when_configured(wire_bootstrap):
    """Purpose: a configured username and password yield one active admin whose
    password verifies. Inputs: the fixture. Output: assertions."""
    factory = wire_bootstrap("root", "a-strong-password")
    session = factory()
    user = UserRepository(session).get_by_username("root")
    session.close()

    assert user is not None
    assert user.role == Role.ADMIN.value
    assert user.is_active
    assert verify_password("a-strong-password", user.password_hash)


def test_is_idempotent_across_restarts(wire_bootstrap):
    """Purpose: running it three times leaves exactly one admin, so a container
    restart never errors. Inputs: the fixture. Output: assertions."""
    wire_bootstrap("root", "a-strong-password")
    wire_bootstrap("root", "a-strong-password")
    factory = wire_bootstrap("root", "a-strong-password")

    session = factory()
    users = UserRepository(session).list_users()
    session.close()
    assert [u.username for u in users] == ["root"]


@pytest.mark.parametrize("username, password", [("", ""), ("admin", ""), ("", "pw-only")])
def test_does_nothing_when_unconfigured(wire_bootstrap, username, password):
    """Purpose: with either value blank - unit tests, local runs - no user is
    written. Inputs: the fixture and blank-ish pairs. Output: assertions."""
    factory = wire_bootstrap(username, password)
    session = factory()
    assert UserRepository(session).list_users() == []
    session.close()
