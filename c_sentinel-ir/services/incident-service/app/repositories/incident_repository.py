"""
incident_repository.py - every SQL statement incident-service runs, in one file.

SQLAlchemy lives here and nowhere else in this service: the business logic in
app/services/ takes a repository and never a Session, which is what keeps it
unit-testable against a fake with no database at all.

Author: Colile
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Incident


class IncidentRepository:
    """
    Purpose: read and write the `incidents` table.
    Inputs:  session - the request-scoped SQLAlchemy session.
    Output:  a repository whose methods return `Incident` rows or None.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, incident_id: int) -> Incident | None:
        """
        Purpose: fetch one incident by id.
        Inputs:  incident_id - the incident's primary key.
        Output:  the `Incident`, or None when no such row exists.
        """
        return self._session.get(Incident, incident_id)

    def list(
        self, status: str | None = None, severity: str | None = None
    ) -> list[Incident]:
        """
        Purpose: the incident listing, optionally narrowed by status and/or
                 severity.
        Inputs:  status, severity - when given, only matching incidents are
                  returned.
        Output:  matching incidents, oldest first, so the ordering is stable
                 between calls rather than whatever the database returns.
        """
        statement = select(Incident).order_by(Incident.id)
        if status is not None:
            statement = statement.where(Incident.status == status)
        if severity is not None:
            statement = statement.where(Incident.severity == severity)
        return list(self._session.scalars(statement))

    def create(self, incident: Incident) -> Incident:
        """
        Purpose: persist a new incident.
        Inputs:  incident - an `Incident` not yet in the database.
        Output:  the persisted incident, with its generated id populated.
        """
        self._session.add(incident)
        self._session.commit()
        self._session.refresh(incident)
        return incident

    def update(self, incident: Incident, changes: dict[str, object]) -> Incident:
        """
        Purpose: apply a set of field changes to an existing incident.
        Inputs:  incident - the row to change, already loaded in this session.
                 changes - attribute name to new value, already validated by
                           the caller.
        Output:  the updated incident.
        """
        for field, value in changes.items():
            setattr(incident, field, value)
        self._session.commit()
        self._session.refresh(incident)
        return incident

    def delete(self, incident: Incident) -> None:
        """
        Purpose: remove an incident permanently.
        Inputs:  incident - the row to delete, already loaded in this session.
        Output:  None.
        """
        self._session.delete(incident)
        self._session.commit()
