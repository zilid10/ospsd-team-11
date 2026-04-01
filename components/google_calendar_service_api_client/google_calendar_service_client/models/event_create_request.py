from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from dateutil.parser import isoparse

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.attendee_request import AttendeeRequest


T = TypeVar("T", bound="EventCreateRequest")


@_attrs_define
class EventCreateRequest:
    """Request model for creating an event.

    Attributes:
        title (str):
        start_time (datetime.datetime):
        end_time (datetime.datetime):
        attendees (list[AttendeeRequest]):
        attachments (list[str]):
        description (None | str | Unset):
        location (None | str | Unset):
    """

    title: str
    start_time: datetime.datetime
    end_time: datetime.datetime
    attendees: list[AttendeeRequest]
    attachments: list[str]
    description: None | str | Unset = UNSET
    location: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        title = self.title

        start_time = self.start_time.isoformat()

        end_time = self.end_time.isoformat()

        attendees = []
        for attendees_item_data in self.attendees:
            attendees_item = attendees_item_data.to_dict()
            attendees.append(attendees_item)

        attachments = self.attachments

        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

        location: None | str | Unset
        if isinstance(self.location, Unset):
            location = UNSET
        else:
            location = self.location

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "title": title,
                "start_time": start_time,
                "end_time": end_time,
                "attendees": attendees,
                "attachments": attachments,
            }
        )
        if description is not UNSET:
            field_dict["description"] = description
        if location is not UNSET:
            field_dict["location"] = location

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.attendee_request import AttendeeRequest

        d = dict(src_dict)
        title = d.pop("title")

        start_time = isoparse(d.pop("start_time"))

        end_time = isoparse(d.pop("end_time"))

        attendees = []
        _attendees = d.pop("attendees")
        for attendees_item_data in _attendees:
            attendees_item = AttendeeRequest.from_dict(attendees_item_data)

            attendees.append(attendees_item)

        attachments = cast(list[str], d.pop("attachments"))

        def _parse_description(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        description = _parse_description(d.pop("description", UNSET))

        def _parse_location(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        location = _parse_location(d.pop("location", UNSET))

        event_create_request = cls(
            title=title,
            start_time=start_time,
            end_time=end_time,
            attendees=attendees,
            attachments=attachments,
            description=description,
            location=location,
        )

        event_create_request.additional_properties = d
        return event_create_request

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
