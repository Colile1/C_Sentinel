"""
test_asset_repository.py - the persistence layer, against real SQL.

SQLite rather than PostgreSQL: what is being tested here is the repository's
own behaviour - lookups, ordering, updates and the conflict it raises - which
is identical on both, and the rule that unit tests need no container holds.

Author: Colile
"""

from __future__ import annotations

import pytest

from common.errors import ConflictError

from app.repositories.asset_repository import AssetRepository


def test_create_assigns_an_id_and_a_created_at(db_session, asset_factory) -> None:
    """A persisted asset comes back with its generated columns filled in."""
    asset = AssetRepository(db_session).create(asset_factory("web-01"))

    assert asset.id is not None
    assert asset.created_at is not None


def test_get_finds_the_asset(db_session, asset_factory) -> None:
    """The lookup a read depends on."""
    repository = AssetRepository(db_session)
    created = repository.create(asset_factory("web-01"))

    found = repository.get(created.id)

    assert found is not None
    assert found.name == "web-01"


def test_get_returns_none_when_absent(db_session) -> None:
    """An unknown id is None, not an exception - the caller decides."""
    assert AssetRepository(db_session).get(999) is None


def test_duplicate_name_raises_conflict(db_session, asset_factory) -> None:
    """
    The unique constraint is the authority, not a prior SELECT - two concurrent
    requests could both pass a check-then-insert.
    """
    repository = AssetRepository(db_session)
    repository.create(asset_factory("web-01"))

    with pytest.raises(ConflictError) as exc:
        repository.create(asset_factory("web-01"))

    assert exc.value.status_code == 409
    assert exc.value.details["field"] == "name"


def test_the_session_still_works_after_a_conflict(db_session, asset_factory) -> None:
    """The rollback leaves the session usable, so one bad insert is not fatal."""
    repository = AssetRepository(db_session)
    repository.create(asset_factory("web-01"))

    with pytest.raises(ConflictError):
        repository.create(asset_factory("web-01"))

    repository.create(asset_factory("web-02"))
    assert len(repository.list()) == 2


def test_list_is_ordered_by_id(db_session, asset_factory) -> None:
    """Stable ordering between calls, rather than the database's whim."""
    repository = AssetRepository(db_session)
    for name in ("charlie", "alpha", "bravo"):
        repository.create(asset_factory(name))

    assert [asset.name for asset in repository.list()] == ["charlie", "alpha", "bravo"]


def test_list_filters_by_asset_type(db_session, asset_factory) -> None:
    """A caller narrowing by type sees only that type."""
    repository = AssetRepository(db_session)
    repository.create(asset_factory("web-01", asset_type="server"))
    repository.create(asset_factory("app-01", asset_type="application"))

    assert [asset.name for asset in repository.list("application")] == ["app-01"]


def test_list_is_empty_on_a_fresh_database(db_session) -> None:
    """No rows means an empty list, not None."""
    assert AssetRepository(db_session).list() == []


def test_update_changes_the_given_fields_only(db_session, asset_factory) -> None:
    """Fields not in `changes` are left exactly as they were."""
    repository = AssetRepository(db_session)
    asset = repository.create(asset_factory("web-01", owner="platform-team"))

    updated = repository.update(asset, {"owner": "sre-team"})

    assert updated.owner == "sre-team"
    assert updated.name == "web-01"


def test_update_name_collision_raises_conflict(db_session, asset_factory) -> None:
    """Renaming into an existing name is a conflict, not a silent overwrite."""
    repository = AssetRepository(db_session)
    repository.create(asset_factory("web-01"))
    other = repository.create(asset_factory("web-02"))

    with pytest.raises(ConflictError):
        repository.update(other, {"name": "web-01"})


def test_delete_removes_the_row(db_session, asset_factory) -> None:
    """A deleted asset can no longer be found."""
    repository = AssetRepository(db_session)
    asset = repository.create(asset_factory("web-01"))

    repository.delete(asset)

    assert repository.get(asset.id) is None
