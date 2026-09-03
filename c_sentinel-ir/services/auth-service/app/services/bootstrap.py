"""
bootstrap.py - create the first admin account, once, at startup.

A fresh `auth_db` holds no users, and every account-creation route requires an
admin token, so nothing could ever create the first user. This module closes
that gap: when `BOOTSTRAP_ADMIN_USERNAME` and `BOOTSTRAP_ADMIN_PASSWORD` are
both set, auth-service creates that one admin at startup and never again.
`scripts/seed_data.py` then logs in as it and creates every other account
through the public API, so seeding still goes through HTTP and no other service
writes to `auth_db`. See DECISIONS.md D-23.

Idempotent: a username that already exists is left untouched, so the stack can
restart without error.

Author: Colile
"""

from __future__ import annotations

import logging

from common.config import get_settings
from common.errors import ConflictError

from app.database import SERVICE_NAME, get_session_factory
from app.repositories.user_repository import UserRepository
from app.schemas import Role
from app.services.user_admin_service import UserAdminService

_logger = logging.getLogger(__name__)


def ensure_bootstrap_admin() -> None:
    """
    Purpose: guarantee one admin account exists, so the first real user can be
             created through `POST /api/v1/auth/users`.
    Inputs:  none; the username and password come from this service's settings.
    Output:  None. Does nothing when the two variables are unset (unit tests,
             local runs), or when the named account already exists.
    Raises:  nothing it does not log first - a database that is not ready must
             not crash-loop the container, matching `init_database`.
    """
    settings = get_settings(SERVICE_NAME)
    username = settings.bootstrap_admin_username.strip()
    password = settings.bootstrap_admin_password

    if not username or not password:
        _logger.info("No bootstrap admin configured; skipping.")
        return

    session = get_session_factory()()
    try:
        admin = UserAdminService(UserRepository(session))
        try:
            admin.create_user(
                username=username,
                email=f"{username}@sentinel.local",
                password=password,
                role=Role.ADMIN,
            )
            _logger.info("Bootstrap admin created: username=%s", username)
        except ConflictError:
            _logger.info("Bootstrap admin already present: username=%s", username)
    except Exception as exc:  # noqa: BLE001 - startup must not crash-loop
        _logger.warning("Could not ensure the bootstrap admin: %s", exc)
    finally:
        session.close()
