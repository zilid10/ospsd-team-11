"""CI-friendly end-to-end tests for the application.

These tests verify the full application wiring — DI registry, client construction,
serialization, and response handling — using a mocked Google service resource.
No real Google credentials are required: they run on any machine, including CI.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from calendar_client_api import CalendarClient, EventCreate, EventUpdate
from calendar_client_api.registry import _ClientRegistry, get_client
from google_calendar_client_impl import GoogleCalendarClient
from google_calendar_client_impl.client_impl import register_google_calendar_client

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.e2e, pytest.mark.circleci]

_NOW = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
_END = _NOW + timedelta(hours=1)


def _fake_event_payload(
    *,
    event_id: str = "ci_evt_001",
    title: str = "CI Test Event",
    start: str = "2026-06-01T10:00:00+00:00",
    end: str = "2026-06-01T11:00:00+00:00",
    extras: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return a realistic Google Calendar event JSON payload."""
    payload: dict[str, object] = {
        "id": event_id,
        "summary": title,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
        "status": "confirmed",
        "description": "CI event description",
        "location": "CI Room",
    }
    if extras:
        payload.update(extras)
    return payload


def _fake_list_payload(events: list[dict[str, object]]) -> dict[str, object]:
    """Wrap a list of event payloads in a Google Calendar list response."""
    return {"kind": "calendar#events", "items": events}


@pytest.fixture(autouse=True)
def _reset_registry() -> Iterator[None]:
    """Ensure the DI registry is clean before and after every test."""
    _ClientRegistry.clear()
    yield
    _ClientRegistry.clear()


@pytest.fixture
def mock_service() -> MagicMock:
    """Return a MagicMock that mimics the Google Calendar service resource."""
    return MagicMock()


@pytest.fixture
def ci_client(mock_service: MagicMock) -> GoogleCalendarClient:
    """Return a GoogleCalendarClient wired to a mock service (no real credentials)."""
    return GoogleCalendarClient(service=mock_service)


def test_registry_wiring_with_mocked_auth() -> None:
    """DI registry resolves to a GoogleCalendarClient satisfying the CalendarClient ABC."""
    with (
        patch(
            "google_calendar_client_impl.client_impl.GoogleCalendarClient._auth_from_env",
            return_value=MagicMock(valid=True, refresh_token=None),
        ),
        patch("google_calendar_client_impl.client_impl.build", return_value=MagicMock()),
    ):
        assert _ClientRegistry._factory is None

        register_google_calendar_client()
        client = get_client()

    assert isinstance(client, GoogleCalendarClient)
    assert isinstance(client, CalendarClient)


def test_create_event_serializes_and_parses_response(ci_client: GoogleCalendarClient, mock_service: MagicMock) -> None:
    """create_event() serializes the request and parses the API response into an Event."""
    payload = _fake_event_payload(event_id="ci_create_001", title="CI Create Event")
    mock_service.events.return_value.insert.return_value.execute.return_value = payload

    event_data = EventCreate(
        title="CI Create Event",
        start_time=_NOW,
        end_time=_END,
        description="CI event description",
        location="CI Room",
        attendees=[],
        attachments=[],
    )

    event = ci_client.create_event(event_data)

    # Verify the API was called with the correct serialized body
    mock_service.events.return_value.insert.assert_called_once_with(
        calendarId="primary",
        body={
            "summary": "CI Create Event",
            "start": {"dateTime": "2026-06-01T10:00:00+00:00"},
            "end": {"dateTime": "2026-06-01T11:00:00+00:00"},
            "description": "CI event description",
            "location": "CI Room",
        },
        supportsAttachments=False,
    )

    # Verify response handling
    assert event.id == "ci_create_001"
    assert event.title == "CI Create Event"
    assert event.description == "CI event description"
    assert event.location == "CI Room"
    assert event.start_time == _NOW
    assert event.end_time == _END


def test_get_event_returns_parsed_event(ci_client: GoogleCalendarClient, mock_service: MagicMock) -> None:
    """get_event() fetches by ID and returns a fully parsed Event."""
    payload = _fake_event_payload(event_id="ci_get_001", title="CI Get Event")
    mock_service.events.return_value.get.return_value.execute.return_value = payload

    event = ci_client.get_event("ci_get_001")

    mock_service.events.return_value.get.assert_called_once_with(
        calendarId="primary",
        eventId="ci_get_001",
    )
    assert event.id == "ci_get_001"
    assert event.title == "CI Get Event"


def test_list_events_returns_all_items(ci_client: GoogleCalendarClient, mock_service: MagicMock) -> None:
    """list_events_between() returns all items from the API list payload."""
    start = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
    end = datetime(2026, 6, 2, 0, 0, tzinfo=UTC)

    payloads = [
        _fake_event_payload(event_id="ci_list_001", title="Event A"),
        _fake_event_payload(event_id="ci_list_002", title="Event B"),
        _fake_event_payload(event_id="ci_list_003", title="Event C"),
    ]
    mock_service.events.return_value.list.return_value.execute.return_value = _fake_list_payload(payloads)

    events = list(ci_client.list_events_between(start, end))

    assert len(events) == len(payloads)
    assert [e.id for e in events] == ["ci_list_001", "ci_list_002", "ci_list_003"]
    assert [e.title for e in events] == ["Event A", "Event B", "Event C"]


def test_update_event_sends_patch_and_returns_updated_event(ci_client: GoogleCalendarClient, mock_service: MagicMock) -> None:
    """update_event() sends only the changed fields and parses the updated response."""
    updated_payload = _fake_event_payload(
        event_id="ci_upd_001",
        title="CI Updated Event",
        extras={"description": "Updated description", "location": "New Room"},
    )
    mock_service.events.return_value.patch.return_value.execute.return_value = updated_payload

    patch = EventUpdate(title="CI Updated Event", description="Updated description", location="New Room")
    event = ci_client.update_event("ci_upd_001", patch)

    mock_service.events.return_value.patch.assert_called_once_with(
        calendarId="primary",
        eventId="ci_upd_001",
        body={"summary": "CI Updated Event", "description": "Updated description", "location": "New Room"},
        supportsAttachments=True,
    )
    assert event.id == "ci_upd_001"
    assert event.title == "CI Updated Event"
    assert event.description == "Updated description"
    assert event.location == "New Room"


def test_delete_event_calls_api(ci_client: GoogleCalendarClient, mock_service: MagicMock) -> None:
    """delete_event() calls the Google Calendar delete API with the correct identifiers."""
    ci_client.delete_event("ci_del_001")

    mock_service.events.return_value.delete.assert_called_once_with(
        calendarId="primary",
        eventId="ci_del_001",
    )
    mock_service.events.return_value.delete.return_value.execute.assert_called_once_with()


def test_full_crud_lifecycle_ci(ci_client: GoogleCalendarClient, mock_service: MagicMock) -> None:
    """Full CRUD workflow against a mocked service: create -> get -> list -> update -> delete."""
    base_payload = _fake_event_payload(event_id="ci_crud_001", title="CI CRUD Event")

    # Create
    mock_service.events.return_value.insert.return_value.execute.return_value = base_payload
    event_data = EventCreate(
        title="CI CRUD Event",
        start_time=_NOW,
        end_time=_END,
        attendees=[],
        attachments=[],
    )
    created = ci_client.create_event(event_data)
    assert created.id == "ci_crud_001"
    assert created.title == "CI CRUD Event"

    # Get
    mock_service.events.return_value.get.return_value.execute.return_value = base_payload
    fetched = ci_client.get_event(created.id)
    assert fetched.id == created.id
    assert fetched.title == created.title

    # List
    mock_service.events.return_value.list.return_value.execute.return_value = _fake_list_payload([base_payload])
    start = _NOW - timedelta(minutes=5)
    end = _END + timedelta(minutes=5)
    events = list(ci_client.list_events_between(start, end))
    assert any(e.id == "ci_crud_001" for e in events)

    # Update
    updated_payload = _fake_event_payload(event_id="ci_crud_001", title="CI CRUD Updated", extras={"description": "Updated"})
    mock_service.events.return_value.patch.return_value.execute.return_value = updated_payload
    patch = EventUpdate(title="CI CRUD Updated", description="Updated")
    updated = ci_client.update_event(created.id, patch)
    assert updated.id == "ci_crud_001"
    assert updated.title == "CI CRUD Updated"
    assert updated.description == "Updated"

    # Delete
    ci_client.delete_event(created.id)
    mock_service.events.return_value.delete.assert_called_once_with(
        calendarId="primary",
        eventId="ci_crud_001",
    )
    mock_service.events.return_value.delete.return_value.execute.assert_called_once_with()
