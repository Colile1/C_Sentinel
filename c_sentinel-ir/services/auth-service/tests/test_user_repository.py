"""
test_user_repository.py - the persistence layer, against real SQL.

SQLite rather than PostgreSQL: what is being tested here is the repository's
own behaviour - lookups, ordering and the conflict it raises - which is
identical on both, and the rule that unit tests need no container holds.

Author: Colile
"""

from __future__ import annotations

import pytest

from common.errors import ConflictError

from app.repositories.user_repository import UserRepository


def test_create_assigns_an_id_and_a_created_at(db_session, user_factory) -> None:
    """A persisted user comes back with its generated columns filled in."""
    user = UserRepository(db_session).create(user_factory("analyst"))

    assert user.id is not None
    assert user.created_at is not None
    assert user.is_active is True


def test_get_by_username_finds_the_user(db_session, user_factory) -> None:
    """The lookup a login depends on."""
    repository = UserRepository(db_session)
    repository.create(user_factory("analyst"))

    found = repository.get_by_username("analyst")

    assert found is not None
    assert found.username == "analyst"


def test_get_by_username_returns_none_when_absent(db_session, user_factory) -> None:
    """An unknown username is None, not an exception - the caller decides."""
    assert UserRepository(db_session).get_by_username("nobody") is None


def test_get_by_username_is_case_sensitive(db_session, user_factory) -> None:
    """Usernames are exact; `Analyst` is not `analyst`."""
    repository = UserRepository(db_session)
    repository.create(user_factory("analyst"))

    assert repository.get_by_username("Analyst") is None


def test_duplicate_username_raises_conflict(db_session, user_factory) -> None:
    """
    The unique constraint is the authority, not a prior SELECT - two concurrent
    requests could both pass a check-then-insert.
    """
    repository = UserRepository(db_session)
    repository.create(user_factory("analyst"))

    with pytest.raises(ConflictError) as exc:
        repository.create(user_factory("analyst"))

    assert exc.value.status_code == 409
    assert exc.value.details["field"] == "username"


def test_the_session_still_works_after_a_conflict(db_session, user_factory) -> None:
    """The rollback leaves the session usable, so one bad insert is not fatal."""
    repository = UserRepository(db_session)
    repository.create(user_factory("analyst"))

    with pytest.raises(ConflictError):
        repository.create(user_factory("analyst"))

    repository.create(user_factory("admin", role="admin"))
    assert len(repository.list_users()) == 2


def test_list_users_is_ordered_by_id(db_session, user_factory) -> None:
    """Stable ordering between calls, rather than the database's whim."""
    repository = UserRepository(db_session)
    for username in ("charlie", "alpha", "bravo"):
        repository.create(user_factory(username))

    assert [user.username for user in repository.list_users()] == [
        "charlie",
        "alpha",
        "bravo",
    ]


def test_list_users_is_empty_on_a_fresh_database(db_session, user_factory) -> None:
    """No rows means an empty list, not None."""
    assert UserRepository(db_session).list_users() == []


def test_repr_never_exposes_the_hash(db_session, user_factory) -> None:
    """A user in a traceback or a log line must not carry its own hash."""
    user = UserRepository(db_session).create(user_factory("analyst"))
    assert user.password_hash not in repr(user)
