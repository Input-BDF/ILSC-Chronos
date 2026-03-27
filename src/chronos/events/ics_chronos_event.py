# -*- coding: utf-8 -*-

# python lib
import logging

# external libs
import icalendar

# own code
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
