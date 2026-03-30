# -*- coding: utf-8 -*-

# python lib
import logging

# external libs
import caldav
import icalendar

# own code
from chronos.calendar_handlers.base_calendar_handler import BaseCalendarHandler
from chronos.events.base_chronos_event import BaseChronosEvent

logger = logging.getLogger(__name__)


class CalDavChronosEvent(BaseChronosEvent):
    def __init__(self, source: "BaseCalendarHandler", caldav_event: caldav.Event):
        super().__init__(source)

        self.calDAV: caldav.Event = caldav_event

    def __repr__(self):
        return f"CalDavChronosEvent - {self.date} | {self.title}"

    @property
    def ical(self) -> icalendar.Event:
        return self.calDAV.icalendar_component
