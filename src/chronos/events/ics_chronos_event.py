# -*- coding: utf-8 -*-

# python lib
from hashlib import md5
from string import Template
from typing import TYPE_CHECKING
import datetime as dt
import logging
import regex
import uuid
import zoneinfo

# external libs
from icalendar import vDDDTypes as icalDate
from icalendar.prop import vCategory
import caldav
import icalendar

# own code
from chronos import helpers
from chronos.calendar_handlers.base_calendar_handler import BaseCalendarHandler
from chronos.events.base_chronos_event import BaseChronosEvent


logger = logging.getLogger(__name__)


class IcsChronosEvent(BaseChronosEvent):
    def __init__(self, source: "BaseCalendarHandler", ics_event: icalendar.Event):
        super().__init__(source)

        self._ics_event: icalendar.Event = ics_event

    def __repr__(self):
        return f"IcsChronosEvent - {self.date} | {self.title}"

    @property
    def ical(self) -> icalendar.Event:
        return self._ics_event

    def create_ical_event(self) -> icalendar.Event:
        new_event = icalendar.Event()

        app_timezone = zoneinfo.ZoneInfo(self.source.app_config.get("app", "timezone"))
        _now = dt.datetime.now().astimezone(app_timezone)

        # set random uuid to support getting arround nextcloud deleting problem
        new_event.add("uid", uuid.uuid1())

        new_event.add("dtstamp", _now)
        new_event.add("dtstart", self.date_start)
        new_event.add("dtend", self.date_end)
        new_event.add("summary", self.prefixed_title)

        if self.source.ignore_descriptions is False and self.description:
            sanitized_description = self.sanitize_description()
            new_event.add("description", sanitized_description)

        if self.location is None:
            new_event.add("location", self.source.default_location)
        else:
            new_event.add("location", self.location)

        new_event.add("categories", self.combine_categories(self.source.tags))
        new_event.add("status", self.status)

        if self.source.color:
            new_event.add("color", self.source.color)

        ####
        # CUSTOM PROPERTIES
        # TODO: Check existence after updating with HIDs (works on rainlendar, android phone [google calendar, jorte]
        new_event.add("X-ILSC-ORIGIN", self.source.app_config.get("app", "app_id"))
        new_event.add("X-ILSC-CREATED", str(_now))
        new_event.add("X-ILSC-CALID", self.source.chronos_id)
        new_event.add("X-ILSC-UID", self.key)

        return new_event

    def set_title_icons(self, sep=" | "):
        try:
            if self.icons:
                _new_title = icalendar.vText(f"{self.icons}{sep}{self.title}")
                self.calDAV.icalendar_component["summary"] = _new_title
                logger.success(f"Event icons set for {self.date} | {self.safe_title}")
                return True
            # return False
        except Exception as ex:
            logger.error(f"Could not set event icons for {self.date} | {self.safe_title} - {ex}")
        return False

    @property
    def icons(self) -> str:
        icons = set(self.categories).intersection(set(self.source.icons))
        icon_str = ""
        if icons:
            for icon in icons:
                icon_str += self.source.icons[icon]
        return icon_str
