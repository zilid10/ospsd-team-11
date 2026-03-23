"""Event adapter that wraps the generated EventResponse as an abstract Event."""

from datetime import datetime

from calendar_client_api.event import Attendee, Event

from google_calendar_service_client.models.attendee_response import AttendeeResponse
from google_calendar_service_client.models.event_response import EventResponse
from google_calendar_service_client.types import Unset


class ServiceCalendarEvent(Event):

    def __init__(self, event_response: EventResponse) -> None:
        self._event = event_response

    @property
    def id(self) -> str:
        return self._event.id

    @property
    def title(self) -> str:
        return self._event.title

    @property
    def start_time(self) -> datetime:
        return self._event.start_time

    @property
    def end_time(self) -> datetime:
        return self._event.end_time

    @property
    def description(self) -> str | None:
        if isinstance(self._event.description, Unset):
            return None
        return self._event.description

    @property
    def location(self) -> str | None:
        if isinstance(self._event.location, Unset):
            return None
        return self._event.location

    @property
    def attendees(self) -> list[Attendee]:
        return [_convert_attendee(a) for a in self._event.attendees]

    @property
    def attachments(self) -> list[str]:
        return self._event.attachments


def _convert_attendee(resp: AttendeeResponse) -> Attendee:
    name = None if isinstance(resp.name, Unset) else resp.name
    return Attendee(email=resp.email, name=name)
