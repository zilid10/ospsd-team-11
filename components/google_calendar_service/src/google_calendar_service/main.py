"""FastAPI service endpoints for the Google Calendar service component."""
from datetime import datetime
from typing import Annotated, Any

import google_calendar_client_impl  # noqa: F401 Registers the concrete client via Dependency Injection
from calendar_client_api import get_client
from calendar_client_api.event import UNSET, Attendee, Event, EventCreate, EventUpdate
from fastapi import FastAPI, Query
from pydantic import BaseModel

app = FastAPI(
    title="Google Calendar Service",
    version="0.1.0",
)
# --- Serialization helpers ---
# Helper functions to convert internal Event models into JSON-safe responses.
def _serialize_attendee(attendee: Attendee) -> dict[str, str | None]:
    """Convert an attendee to a JSON-safe dictionary."""
    return {
        "email": attendee.email,
        "name": attendee.name,
    }


def _serialize_event(event: Event) -> dict[str, Any]:
    """Convert an event to a JSON-safe dictionary."""
    return {
        "id": event.id,
        "title": event.title,
        "start_time": event.start_time.isoformat(),
        "end_time": event.end_time.isoformat(),
        "description": event.description,
        "location": event.location,
        "attendees": [_serialize_attendee(attendee) for attendee in event.attendees],
        "attachments": event.attachments,
    }

# Convert FastAPI request models into EventCreate/EventUpdate for the client interface.
class AttendeeRequest(BaseModel):
    """Request model for an event attendee."""

    email: str
    name: str | None = None


class EventCreateRequest(BaseModel):
    """Request model for creating an event."""

    title: str
    start_time: datetime
    end_time: datetime
    attendees: list[AttendeeRequest]
    attachments: list[str]
    description: str | None = None
    location: str | None = None

    def to_event_create(self) -> EventCreate:
        """Convert request data to EventCreate."""
        return EventCreate(
            title=self.title,
            start_time=self.start_time,
            end_time=self.end_time,
            attendees=[
                Attendee(email=attendee.email, name=attendee.name)
                for attendee in self.attendees
            ],
            attachments=self.attachments,
            description=self.description,
            location=self.location,
        )

class EventUpdateRequest(BaseModel):
    """Request model for updating an event."""

    title: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    description: str | None = None
    location: str | None = None

    def to_event_update(self) -> EventUpdate:
        """Convert request data to EventUpdate."""
        return EventUpdate(
            title=self.title if self.title is not None else UNSET,
            start_time=self.start_time if self.start_time is not None else UNSET,
            end_time=self.end_time if self.end_time is not None else UNSET,
            description=self.description if self.description is not None else UNSET,
            location=self.location if self.location is not None else UNSET,
        )

@app.get("/health")
def health() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}


@app.get("/auth/login")
def login() -> dict[str, str]:
    """Start the OAuth login flow."""
    return {"message": "OAuth login not implemented yet"}


@app.get("/auth/callback")
def callback(code: Annotated[str | None, Query()] = None) -> dict[str, str]:
    """Handle the OAuth callback from the provider."""
    if code is None:
        return {"message": "Missing authorization code"}
    return {"message": "OAuth callback not implemented yet"}


@app.get("/events")
def list_events(
    max_results: Annotated[int, Query(ge=1)] = 10) -> dict[str, list[dict[str, Any]]]:
    """List calendar events."""
    client = get_client()
    events = client.list_events(max_results=max_results)
    return {"events": [_serialize_event(event) for event in events]}

@app.get("/events/{event_id}")
def get_event(event_id: str) -> dict[str, dict[str, Any]]:
    """Get a single calendar event by ID."""
    client = get_client()
    event = client.get_event(event_id)
    return {"event": _serialize_event(event)}

@app.post("/events")
def create_event(event: EventCreateRequest) -> dict[str, dict[str, Any]]:
    """Create a calendar event."""
    client = get_client()
    created_event = client.create_event(event.to_event_create())
    return {"event": _serialize_event(created_event)}

@app.patch("/events/{event_id}")
def update_event(event_id: str, event: EventUpdateRequest) -> dict[str, dict[str, Any]]:
    """Update a calendar event."""
    client = get_client()
    updated_event = client.update_event(event_id, event.to_event_update())
    return {"event": _serialize_event(updated_event)}

@app.delete("/events/{event_id}")
def delete_event(event_id: str) -> dict[str, str]:
    """Delete a calendar event."""
    client = get_client()
    client.delete_event(event_id)
    return {"status": "deleted"}
