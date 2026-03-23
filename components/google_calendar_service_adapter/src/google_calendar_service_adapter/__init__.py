import calendar_client_api

from google_calendar_service_adapter.client_adapter import ServiceCalendarClient as ServiceCalendarClient
from google_calendar_service_adapter.event_adapter import ServiceCalendarEvent as ServiceCalendarEvent


def register_service_calendar_client(base_url: str = "http://localhost:8000") -> None:
    calendar_client_api.register_client(lambda: ServiceCalendarClient(base_url=base_url))

register_service_calendar_client()
