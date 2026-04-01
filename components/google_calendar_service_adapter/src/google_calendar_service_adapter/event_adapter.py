"""Event adapter that wraps the generated EventResponse as an abstract Event."""

from datetime import datetime

from calendar_client_api.event import Attendee, Event
from google_calendar_service_client.models.attendee_response import AttendeeResponse
from google_calendar_service_client.models.event_response import EventResponse
from google_calendar_service_client.types import Unset


class ServiceCalendarEvent(Event):
    """Implements the abstract Event by wrapping a generated EventResponse."""

    def __init__(self, event_response: EventResponse) -> None:
        """Initialize with a generated EventResponse."""
        self._event = event_response

    @property
    def id(self) -> str:
        """Return the event ID."""
        return self._event.id

    @property
    def title(self) -> str:
        """Return the event title."""
        return self._event.title

    @property
    def start_time(self) -> datetime:
        """Return the start datetime."""
        return self._event.start_time

    @property
    def end_time(self) -> datetime:
        """Return the end datetime."""
        return self._event.end_time

    @property
    def description(self) -> str | None:
        """Return the description, or None if unset."""
        if isinstance(self._event.description, Unset):
            return None
        return self._event.description

    @property
    def location(self) -> str | None:
        """Return the location, or None if unset."""
        if isinstance(self._event.location, Unset):
            return None
        return self._event.location

    @property
    def attendees(self) -> list[Attendee]:
        """Return attendees converted from the generated response."""
        return [_convert_attendee(a) for a in self._event.attendees]

    @property
    def attachments(self) -> list[str]:
        """Return attachment URLs."""
        return self._event.attachments


def _convert_attendee(resp: AttendeeResponse) -> Attendee:
    name = None if isinstance(resp.name, Unset) else resp.name
    return Attendee(email=resp.email, name=name)
