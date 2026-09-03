"""
test_incident_repository.py - the persistence layer, against real SQL.

SQLite rather than PostgreSQL: what is being tested here is the repository's
own behaviour - lookups, ordering, filtering and updates - which is identical
on both, and the rule that unit tests need no container holds.

Author: Colile
"""

from __future__ import annotations

from app.repositories.incident_repository import IncidentRepository


def test_create_assigns_an_id_and_timestamps(db_session, incident_factory) -> None:
    """A persisted incident comes back with its generated columns filled in."""
    incident = IncidentRepository(db_session).create(incident_factory())

    assert incident.id is not None
    assert incident.created_at is not None
    assert incident.updated_at is not None


def test_get_finds_the_incident(db_session, incident_factory) -> None:
    """The lookup a read depends on."""
    repository = IncidentRepository(db_session)
    created = repository.create(incident_factory())

    found = repository.get(created.id)

    assert found is not None
    assert found.title == created.title


def test_get_returns_none_when_absent(db_session) -> None:
    """An unknown id is None, not an exception - the caller decides."""
    assert IncidentRepository(db_session).get(999) is None


def test_list_is_ordered_by_id(db_session, incident_factory) -> None:
    """Stable ordering between calls, rather than the database's whim."""
    repository = IncidentRepository(db_session)
    for title in ("charlie", "alpha", "bravo"):
        repository.create(incident_factory(title=title))

    assert [incident.title for incident in repository.list()] == [
        "charlie",
        "alpha",
        "bravo",
    ]


def test_list_filters_by_status(db_session, incident_factory) -> None:
    """A caller narrowing by status sees only that status."""
    repository = IncidentRepository(db_session)
    repository.create(incident_factory(title="open-one", status="OPEN"))
    repository.create(incident_factory(title="resolved-one", status="RESOLVED"))

    assert [i.title for i in repository.list(status="RESOLVED")] == ["resolved-one"]


def test_list_filters_by_severity(db_session, incident_factory) -> None:
    """A caller narrowing by severity sees only that severity."""
    repository = IncidentRepository(db_session)
    repository.create(incident_factory(title="low-one", severity="LOW"))
    repository.create(incident_factory(title="high-one", severity="HIGH"))

    assert [i.title for i in repository.list(severity="HIGH")] == ["high-one"]


def test_list_is_empty_on_a_fresh_database(db_session) -> None:
    """No rows means an empty list, not None."""
    assert IncidentRepository(db_session).list() == []


def test_update_changes_the_given_fields_only(db_session, incident_factory) -> None:
    """Fields not in `changes` are left exactly as they were."""
    repository = IncidentRepository(db_session)
    incident = repository.create(incident_factory(status="OPEN"))

    updated = repository.update(incident, {"status": "TRIAGED"})

    assert updated.status == "TRIAGED"
    assert updated.title == incident.title


def test_delete_removes_the_row(db_session, incident_factory) -> None:
    """A deleted incident can no longer be found."""
    repository = IncidentRepository(db_session)
    incident = repository.create(incident_factory())

    repository.delete(incident)

    assert repository.get(incident.id) is None
