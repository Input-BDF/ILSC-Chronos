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
