"""FastAPI service endpoints for the Google Calendar service component."""

from typing import Annotated

import google_calendar_client_impl  # noqa: F401 Registers the concrete client via Dependency Injection
from calendar_client_api import get_client
from fastapi import FastAPI, Query

from google_calendar_service.models import (
    EventCreateRequest,
    EventEnvelope,
    EventsEnvelope,
    EventUpdateRequest,
    StatusResponse,
    to_event_response,
)

app = FastAPI(
    title="Google Calendar Service",
    version="0.1.0",
)


@app.get("/health")
def health() -> StatusResponse:
    """Return service health status."""
    return StatusResponse(status="ok")


@app.get("/auth/login")
async def login() -> StatusResponse:
    """Start the OAuth login flow."""
    return StatusResponse(status="login initiated")


@app.post("/auth/logout")
async def logout() -> StatusResponse:
    """Log the user out by clearing their session."""
    return StatusResponse(status="logged out")


@app.get("/auth/callback")
def callback(code: Annotated[str | None, Query()] = None) -> StatusResponse:
    """Handle the OAuth callback from the provider."""
    if code is None:
        return StatusResponse(status="Missing authorization code")
    return StatusResponse(status="OAuth callback not implemented yet")


@app.get("/events")
def list_events(max_results: Annotated[int, Query(ge=1)] = 10) -> EventsEnvelope:
    """List calendar events."""
    client = get_client()
    events = client.list_events(max_results=max_results)
    return EventsEnvelope(events=[to_event_response(event) for event in events])


@app.get("/events/{event_id}")
def get_event(event_id: str) -> EventEnvelope:
    """Get a single calendar event by ID."""
    client = get_client()
    event = client.get_event(event_id)
    return EventEnvelope(event=to_event_response(event))


@app.post("/events")
def create_event(event: EventCreateRequest) -> EventEnvelope:
    """Create a calendar event."""
    client = get_client()
    created_event = client.create_event(event.to_event_create())
    return EventEnvelope(event=to_event_response(created_event))


@app.patch("/events/{event_id}")
def update_event(event_id: str, event: EventUpdateRequest) -> EventEnvelope:
    """Update a calendar event."""
    client = get_client()
    updated_event = client.update_event(event_id, event.to_event_update())
    return EventEnvelope(event=to_event_response(updated_event))


@app.delete("/events/{event_id}")
def delete_event(event_id: str) -> StatusResponse:
    """Delete a calendar event."""
    client = get_client()
    client.delete_event(event_id)
    return StatusResponse(status="deleted")
