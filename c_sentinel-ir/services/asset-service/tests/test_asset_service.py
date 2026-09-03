"""
test_asset_service.py - the asset business logic, against a fake repository.

Pure unit tests: no database, no container, no network - proving the rules
`AssetService` is responsible for, in particular that only a CRITICAL read
emits `ASSET_ACCESSED`.

Author: Colile
"""

from __future__ import annotations

import pytest

from common.errors import NotFoundError

from app.schemas import AssetCreate, AssetUpdate, Criticality
from app.services.asset_service import AssetService

CORRELATION_ID = "corr-test0000001"


def test_create_persists_the_asset(asset_service: AssetService) -> None:
    """A valid creation request becomes a stored asset."""
    created = asset_service.create(
        AssetCreate(
            name="web-01",
            asset_type="server",
            criticality=Criticality.LOW,
            owner="platform-team",
            location="eu-west-1",
        )
    )

    assert created.id is not None
    assert created.name == "web-01"
    assert created.criticality == "LOW"


def test_get_unknown_id_raises_not_found(asset_service: AssetService) -> None:
    """An id with no row raises NotFoundError, naming the field."""
    with pytest.raises(NotFoundError) as exc:
        asset_service.get(999, correlation_id=CORRELATION_ID)

    assert exc.value.status_code == 404
    assert exc.value.details["field"] == "asset_id"


def test_reading_a_low_asset_emits_no_event(
    asset_service: AssetService, captured_events
) -> None:
    """Routine traffic against a non-CRITICAL asset stays silent."""
    created = asset_service.create(
        AssetCreate(
            name="web-01",
            asset_type="server",
            criticality=Criticality.LOW,
            owner="platform-team",
            location="eu-west-1",
        )
    )

    asset_service.get(created.id, correlation_id=CORRELATION_ID)

    assert captured_events == []


def test_reading_a_critical_asset_emits_exactly_one_event(
    asset_service: AssetService, captured_events
) -> None:
    """The one signal Phase 2 reads for sensitive-asset access."""
    created = asset_service.create(
        AssetCreate(
            name="core-db",
            asset_type="database",
            criticality=Criticality.CRITICAL,
            owner="platform-team",
            location="eu-west-1",
        )
    )

    asset_service.get(created.id, correlation_id=CORRELATION_ID)
    asset_service.get(created.id, correlation_id=CORRELATION_ID)

    assert len(captured_events) == 2
    event = captured_events[0]
    assert event["eventType"] == "ASSET_ACCESSED"
    assert event["affectedEntity"] == f"asset-{created.id}"
    assert event["correlationId"] == CORRELATION_ID


def test_update_unknown_id_raises_not_found(asset_service: AssetService) -> None:
    """Updating a non-existent asset raises the same NotFoundError as get."""
    with pytest.raises(NotFoundError):
        asset_service.update(999, AssetUpdate(owner="sre-team"))


def test_update_changes_only_supplied_fields(asset_service: AssetService) -> None:
    """Fields left unset in the request are untouched."""
    created = asset_service.create(
        AssetCreate(
            name="web-01",
            asset_type="server",
            criticality=Criticality.LOW,
            owner="platform-team",
            location="eu-west-1",
        )
    )

    updated = asset_service.update(created.id, AssetUpdate(owner="sre-team"))

    assert updated.owner == "sre-team"
    assert updated.name == "web-01"


def test_update_criticality_stores_the_plain_value(asset_service: AssetService) -> None:
    """The enum is unwrapped to its string value before persistence."""
    created = asset_service.create(
        AssetCreate(
            name="web-01",
            asset_type="server",
            criticality=Criticality.LOW,
            owner="platform-team",
            location="eu-west-1",
        )
    )

    updated = asset_service.update(
        created.id, AssetUpdate(criticality=Criticality.HIGH)
    )

    assert updated.criticality == "HIGH"


def test_delete_unknown_id_raises_not_found(asset_service: AssetService) -> None:
    """Deleting a non-existent asset raises NotFoundError rather than no-op."""
    with pytest.raises(NotFoundError):
        asset_service.delete(999)


def test_delete_removes_the_asset(asset_service: AssetService) -> None:
    """A deleted asset can no longer be fetched."""
    created = asset_service.create(
        AssetCreate(
            name="web-01",
            asset_type="server",
            criticality=Criticality.LOW,
            owner="platform-team",
            location="eu-west-1",
        )
    )

    asset_service.delete(created.id)

    with pytest.raises(NotFoundError):
        asset_service.get(created.id, correlation_id=CORRELATION_ID)


def test_list_returns_created_assets(asset_service: AssetService) -> None:
    """The listing reflects what has been created."""
    asset_service.create(
        AssetCreate(
            name="web-01",
            asset_type="server",
            criticality=Criticality.LOW,
            owner="platform-team",
            location="eu-west-1",
        )
    )
    asset_service.create(
        AssetCreate(
            name="app-01",
            asset_type="application",
            criticality=Criticality.LOW,
            owner="platform-team",
            location="eu-west-1",
        )
    )

    assert [asset.name for asset in asset_service.list()] == ["web-01", "app-01"]
    assert [asset.name for asset in asset_service.list("application")] == ["app-01"]
