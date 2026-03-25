"""Tests for the Google Calendar FastAPI service."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

import google_calendar_service.main as main_module
import pytest
from calendar_client_api.event import Attendee, Event, EventCreate, EventUpdate
from fastapi.testclient import TestClient
from google_calendar_service.main import app

HTTP_OK = 200
DEFAULT_MAX_RESULTS = 10

client = TestClient(app)


@pytest.fixture(autouse=True)
def override_get_client_dependency() -> Iterator[None]:
    """Override the FastAPI get_client dependency with the fake client for these tests."""
    app.dependency_overrides[main_module.get_client] = fake_get_client
    yield
    app.dependency_overrides.pop(main_module.get_client, None)


@dataclass(frozen=True)
class FakeEventData:
    """Concrete event data used to back a fake Event implementation."""

    event_id: str
    title: str
    start_time: datetime
    end_time: datetime
    description: str | None = None
    location: str | None = None
    attendees: list[Attendee] | None = None
    attachments: list[str] | None = None


class FakeEvent(Event):
    """Fake event used for service tests."""

    def __init__(self, data: FakeEventData) -> None:
        """Initialize a fake event from test data."""
        self._data = data

    @property
    def id(self) -> str:
        """Return the event ID."""
        return self._data.event_id

    @property
    def title(self) -> str:
        """Return the event title."""
        return self._data.title

    @property
    def start_time(self) -> datetime:
        """Return the start time."""
        return self._data.start_time

    @property
    def end_time(self) -> datetime:
        """Return the end time."""
        return self._data.end_time

    @property
    def description(self) -> str | None:
        """Return the description."""
        return self._data.description

    @property
    def location(self) -> str | None:
        """Return the location."""
        return self._data.location

    @property
    def attendees(self) -> list[Attendee]:
        """Return the attendees."""
        return self._data.attendees or []

    @property
    def attachments(self) -> list[str]:
        """Return the attachments."""
        return self._data.attachments or []


class FakeCalendarClient:
    """Fake calendar client used for service tests."""

    def list_events(self, max_results: int = DEFAULT_MAX_RESULTS) -> Iterable[Event]:
        """Return fake events."""
        assert max_results == DEFAULT_MAX_RESULTS
        return [
            FakeEvent(
                FakeEventData(
                    event_id="test_123",
                    title="Networking Event",
                    start_time=datetime(2026, 3, 18, 10, 0, tzinfo=UTC),
                    end_time=datetime(2026, 3, 18, 11, 0, tzinfo=UTC),
                    description="NYU event",
                    location="2 MetroTech",
                    attendees=[Attendee(email="test@example.com", name="Joe")],
                    attachments=["https://example.com/doc"],
                )
            ),
        ]

    def get_event(self, event_id: str) -> Event:
        """Return one fake event by ID."""
        assert event_id == "test_123"
        return FakeEvent(
            FakeEventData(
                event_id="test_123",
                title="Networking Event",
                start_time=datetime(2026, 3, 18, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 3, 18, 11, 0, tzinfo=UTC),
                description="NYU event",
                location="2 MetroTech",
                attendees=[Attendee(email="test@example.com", name="Joe")],
                attachments=["https://example.com/doc"],
            )
        )

    def create_event(self, event_create: EventCreate) -> Event:
        """Return a created fake event."""
        assert event_create.title == "Java Exam"
        assert event_create.description == "Java Midterm"
        assert event_create.location == "2 MetroTech"
        assert len(event_create.attendees) == 1
        assert event_create.attendees[0] == Attendee(email="designer@example.com", name="Designer")
        assert event_create.attachments == ["https://example.com/spec"]

        return FakeEvent(
            FakeEventData(
                event_id="evt_created",
                title=event_create.title,
                start_time=event_create.start_time,
                end_time=event_create.end_time,
                description=event_create.description,
                location=event_create.location,
                attendees=event_create.attendees,
                attachments=event_create.attachments,
            )
        )

    def update_event(self, event_id: str, event_update: EventUpdate) -> Event:
        """Return an updated fake event."""
        assert event_id == "test_123"
        assert event_update.title == "Updated Java Midterm"
        assert event_update.location == "New 2 MetroTech Room"

        return FakeEvent(
            FakeEventData(
                event_id="test_123",
                title="Updated Java Midterm",
                start_time=datetime(2026, 3, 18, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 3, 18, 11, 0, tzinfo=UTC),
                description=None,
                location="2 MetroTech Room",
                attendees=[Attendee(email="test@example.com", name="Joe")],
                attachments=["https://example.com/doc"],
            )
        )

    def delete_event(self, event_id: str) -> None:
        """Delete a fake event."""
        assert event_id == "test_123"


def fake_get_client() -> FakeCalendarClient:
    """Return a fake calendar client."""
    return FakeCalendarClient()


class TestHealthEndpoint:
    """Tests for the health endpoint."""

    def test_returns_ok_status(self) -> None:
        """Return a successful health response."""
        response = client.get("/health")

        assert response.status_code == HTTP_OK
        assert response.json() == {"status": "ok"}


class TestListEventsEndpoint:
    """Tests for the list events endpoint."""

    def test_returns_serialized_events(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Return serialized event data from the client."""
        response = client.get("/events")

        assert response.status_code == HTTP_OK
        assert response.json() == {
            "events": [
                {
                    "id": "test_123",
                    "title": "Networking Event",
                    "start_time": "2026-03-18T10:00:00Z",
                    "end_time": "2026-03-18T11:00:00Z",
                    "description": "NYU event",
                    "location": "2 MetroTech",
                    "attendees": [
                        {
                            "email": "test@example.com",
                            "name": "Joe",
                        },
                    ],
                    "attachments": ["https://example.com/doc"],
                },
            ],
        }


class TestGetEventEndpoint:
    """Tests for the get event endpoint."""

    def test_returns_serialized_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Return one serialized event by ID."""
        response = client.get("/events/test_123")

        assert response.status_code == HTTP_OK
        assert response.json() == {
            "event": {
                "id": "test_123",
                "title": "Networking Event",
                "start_time": "2026-03-18T10:00:00Z",
                "end_time": "2026-03-18T11:00:00Z",
                "description": "NYU event",
                "location": "2 MetroTech",
                "attendees": [
                    {
                        "email": "test@example.com",
                        "name": "Joe",
                    },
                ],
                "attachments": ["https://example.com/doc"],
            },
        }


class TestCreateEventEndpoint:
    """Tests for the create event endpoint."""

    def test_creates_and_returns_serialized_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Create an event and return serialized event data."""
        response = client.post(
            "/events",
            json={
                "title": "Java Exam",
                "start_time": "2026-03-20T14:00:00+00:00",
                "end_time": "2026-03-20T15:00:00+00:00",
                "attendees": [
                    {
                        "email": "designer@example.com",
                        "name": "Designer",
                    },
                ],
                "attachments": ["https://example.com/spec"],
                "description": "Java Midterm",
                "location": "2 MetroTech",
            },
        )

        assert response.status_code == HTTP_OK
        assert response.json() == {
            "event": {
                "id": "evt_created",
                "title": "Java Exam",
                "start_time": "2026-03-20T14:00:00Z",
                "end_time": "2026-03-20T15:00:00Z",
                "description": "Java Midterm",
                "location": "2 MetroTech",
                "attendees": [
                    {
                        "email": "designer@example.com",
                        "name": "Designer",
                    },
                ],
                "attachments": ["https://example.com/spec"],
            },
        }


class TestUpdateEventEndpoint:
    """Tests for the update event endpoint."""

    def test_updates_and_returns_serialized_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Update an event and return serialized event data."""
        response = client.patch(
            "/events/test_123",
            json={
                "title": "Updated Java Midterm",
                "location": "New 2 MetroTech Room",
            },
        )

        assert response.status_code == HTTP_OK
        assert response.json() == {
            "event": {
                "id": "test_123",
                "title": "Updated Java Midterm",
                "start_time": "2026-03-18T10:00:00Z",
                "end_time": "2026-03-18T11:00:00Z",
                "description": None,
                "location": "2 MetroTech Room",
                "attendees": [
                    {
                        "email": "test@example.com",
                        "name": "Joe",
                    },
                ],
                "attachments": ["https://example.com/doc"],
            },
        }


class TestDeleteEventEndpoint:
    """Tests for the delete event endpoint."""

    def test_deletes_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Delete an event and return confirmation."""
        response = client.delete("/events/test_123")

        assert response.status_code == HTTP_OK
        assert response.json() == {"status": "deleted"}
