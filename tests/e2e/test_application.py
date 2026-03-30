"""End-to-End tests for the application.

These tests run the complete workflow against real Google Calendar infrastructure
using credentials supplied via environment variables.

Required environment variables (or a .env file):
    GOOGLE_CALENDAR_CLIENT_ID
    GOOGLE_CALENDAR_CLIENT_SECRET
    GOOGLE_CALENDAR_REFRESH_TOKEN
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from calendar_client_api import CalendarClient, Event, EventCreate, EventUpdate
from calendar_client_api.registry import _ClientRegistry, get_client
from google_calendar_client_impl import GoogleCalendarClient
from google_calendar_client_impl.client_impl import load_env, register_google_calendar_client

if TYPE_CHECKING:
    from collections.abc import Iterator

load_env()

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.local_credentials,
]


_E2E_TAG = "[e2e-test]"  # tag injected into every test event title for easy identification


def _future_event_create(
    *,
    title: str = "E2E Test Event",
    offset_hours: int = 1,
    duration_hours: int = 1,
) -> EventCreate:
    """Return an EventCreate whose window starts *offset_hours* from now."""
    start = datetime.now(tz=UTC) + timedelta(hours=offset_hours)
    end = start + timedelta(hours=duration_hours)
    return EventCreate(
        title=f"{_E2E_TAG} {title}",
        start_time=start,
        end_time=end,
        description="Created by automated e2e test suite - safe to delete.",
        location="Virtual",
        attendees=[],
        attachments=[],
    )


@pytest.fixture(autouse=True)
def _reset_registry() -> Iterator[None]:
    """Ensure the DI registry is clean before and after every test."""
    _ClientRegistry.clear()
    yield
    _ClientRegistry.clear()


@pytest.fixture
def registered_client() -> GoogleCalendarClient:
    """Register the real Google Calendar client and return it via get_client()."""
    register_google_calendar_client()
    try:
        client = get_client()
    except RuntimeError as exc:
        pytest.skip(f"Skipping e2e test: local Google credentials unavailable ({exc})")
    assert isinstance(client, GoogleCalendarClient)
    return client


@pytest.fixture
def transient_event(registered_client: GoogleCalendarClient) -> Iterator[Event]:
    """Create a test event before the test and delete it afterward (even on failure)."""
    event_data = _future_event_create(title="Transient Fixture Event")
    event = registered_client.create_event(event_data)
    yield event
    # Best-effort cleanup
    with contextlib.suppress(Exception):
        registered_client.delete_event(event.id)


def test_client_creation_via_registry() -> None:
    """Client creation: registering the factory and resolving via DI returns a live client."""
    assert _ClientRegistry._factory is None, "Registry must be empty at test start."

    register_google_calendar_client()

    assert _ClientRegistry._factory is not None, "Factory must be registered after call."

    try:
        client = get_client()
    except RuntimeError as exc:
        pytest.skip(f"Skipping e2e test: local Google credentials unavailable ({exc})")

    assert isinstance(client, GoogleCalendarClient), f"get_client() must return a GoogleCalendarClient, got {type(client)}"
    assert isinstance(client, CalendarClient), "GoogleCalendarClient must satisfy the CalendarClient ABC."


def test_create_event_returns_valid_event(registered_client: GoogleCalendarClient) -> None:
    """API call: create_event posts to the real Google Calendar and returns a structured Event."""
    event_data = _future_event_create(title="Create Validation")

    event = registered_client.create_event(event_data)
    created_event_id = event.id

    try:
        # response handling assertions
        assert event.id, "Created event must have a non-empty id."
        assert event.title == event_data.title, f"Title mismatch: expected {event_data.title!r}, got {event.title!r}"
        assert event.description == event_data.description
        assert event.location == event_data.location
        assert event.start_time.date() == event_data.start_time.date()
        assert event.end_time.date() == event_data.end_time.date()
        assert isinstance(event.attendees, list)
        assert isinstance(event.attachments, list)
    finally:
        # Best-effort cleanup
        with contextlib.suppress(Exception):
            registered_client.delete_event(created_event_id)


def test_get_event_returns_matching_event(
    registered_client: GoogleCalendarClient,
    transient_event: Event,
) -> None:
    """API call: get_event retrieves the previously created event by ID."""
    fetched = registered_client.get_event(transient_event.id)

    assert isinstance(fetched, Event)
    assert fetched.id == transient_event.id, f"Event id mismatch: expected {transient_event.id!r}, got {fetched.id!r}"
    assert fetched.title == transient_event.title
    assert fetched.start_time.date() == transient_event.start_time.date()
    assert fetched.end_time.date() == transient_event.end_time.date()


def test_list_events_includes_created_event(
    registered_client: GoogleCalendarClient,
    transient_event: Event,
) -> None:
    """API call: list_events returns an iterable that includes the newly created event."""
    now = datetime.now(tz=UTC)
    window_start = now - timedelta(minutes=5)
    window_end = now + timedelta(hours=48)

    events = list(registered_client.list_events_between(window_start, window_end))

    assert isinstance(events, list), "list_events_between must return a list."
    event_ids = [e.id for e in events]
    assert transient_event.id in event_ids, (
        f"Newly created event {transient_event.id!r} not found in list response. Found ids: {event_ids!r}"
    )


def test_update_event_applies_changes(
    registered_client: GoogleCalendarClient,
    transient_event: Event,
) -> None:
    """API call: update_event patches the event and the response reflects the changes."""
    new_title = f"{_E2E_TAG} Updated Title"
    new_description = "Updated by e2e test."
    new_location = "Conference Room B"

    patch = EventUpdate(
        title=new_title,
        description=new_description,
        location=new_location,
    )

    updated = registered_client.update_event(transient_event.id, patch)

    assert updated.id == transient_event.id, "Event id must not change after update."
    assert updated.title == new_title, f"Title not updated: expected {new_title!r}, got {updated.title!r}"
    assert updated.description == new_description
    assert updated.location == new_location


def test_delete_event_removes_event(registered_client: GoogleCalendarClient) -> None:
    """API call: delete_event removes the event from future listings."""
    event_data = _future_event_create(title="Delete Validation")
    event = registered_client.create_event(event_data)
    event_id = event.id

    # Confirm the event is visible before deletion
    window_start = event.start_time - timedelta(minutes=5)
    window_end = event.end_time + timedelta(minutes=5)
    events_before = [e.id for e in registered_client.list_events_between(window_start, window_end)]
    assert event_id in events_before, f"Precondition failed: event {event_id!r} not found before deletion."

    # Action under test
    registered_client.delete_event(event_id)

    # After deletion the event must not appear in the same listing window
    events_after = [e.id for e in registered_client.list_events_between(window_start, window_end)]
    assert event_id not in events_after, f"Event {event_id!r} still appears in list after deletion."


def test_full_crud_lifecycle() -> None:
    """Complete workflow: client creation -> create -> get -> list -> update -> delete."""
    # 1. Client creation via DI registry
    register_google_calendar_client()
    try:
        client = get_client()
    except RuntimeError as exc:
        pytest.skip(f"Skipping e2e test: local Google credentials unavailable ({exc})")

    assert isinstance(client, CalendarClient)
    assert isinstance(client, GoogleCalendarClient)

    event_id: str | None = None
    try:
        # 2. Create an event
        event_data = _future_event_create(title="Full CRUD Lifecycle")
        created = client.create_event(event_data)

        assert created.id, "create_event must return an event with a non-empty id."
        assert _E2E_TAG in created.title
        event_id = created.id

        # 3. Get the event
        fetched = client.get_event(event_id)

        assert fetched.id == event_id
        assert fetched.title == created.title

        # 4. List (between)
        now = datetime.now(tz=UTC)
        events_in_window = list(
            client.list_events_between(
                now - timedelta(minutes=5),
                now + timedelta(hours=48),
            )
        )
        found_ids = [e.id for e in events_in_window]
        assert event_id in found_ids, f"Created event {event_id!r} not returned by list_events_between."

        # 5. Update the event
        updated_title = f"{_E2E_TAG} Updated CRUD Event"
        patch = EventUpdate(title=updated_title, description="Updated description.")
        updated = client.update_event(event_id, patch)

        assert updated.id == event_id
        assert updated.title == updated_title
        assert updated.description == "Updated description."
        assert updated.location == fetched.location
        assert updated.start_time == fetched.start_time
        assert updated.end_time == fetched.end_time

        # 6. Delete the event
        # Capture the listing window from the created event's time before deleting
        window_start = created.start_time - timedelta(minutes=5)
        window_end = created.end_time + timedelta(minutes=5)
        deleted_id = event_id

        client.delete_event(event_id)

        event_id = None  # signal cleanup is done

        # 7. Verify deletion: cancelled events are excluded from list_events_between
        ids_after_delete = [e.id for e in client.list_events_between(window_start, window_end)]
        assert deleted_id not in ids_after_delete, f"Deleted event {deleted_id!r} still appears in list after deletion."

    finally:
        # Cleanup in case the test failed before the delete step
        if event_id is not None:
            with contextlib.suppress(Exception):
                client.delete_event(event_id)
