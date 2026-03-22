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


class CalDavChronosEvent(BaseChronosEvent):
    def __init__(self, source: "BaseCalendarHandler", caldav_event: caldav.Event):
        super().__init__(source)

        self.calDAV: caldav.Event = caldav_event

    def __repr__(self):
        return f"CalDavChronosEvent - {self.date} | {self.title}"

    @property
    def ical(self) -> icalendar.Event:
        return self.calDAV.icalendar_component

    def update_calDaV_event(self, src_event):
        """update data from given event"""

        self.calDAV.icalendar_component["summary"] = src_event.prefixed_title

        if src_event.description is None and "description" in self.calDAV.vobject_instance.vevent.contents.keys():
            # remove description from VEVENT cause it should not be there
            self.calDAV.vobject_instance.vevent.remove(self.calDAV.vobject_instance.vevent.description)

        if src_event.source.ignore_descriptions is False and src_event.description:
            # add description to VEVENT
            if "description" not in self.calDAV.vobject_instance.vevent.contents.keys():
                self.calDAV.vobject_instance.vevent.add("description")
            self.calDAV.vobject_instance.vevent.description.value = src_event.sanitize_description()

        if src_event.location is None:
            self.calDAV.icalendar_component["location"] = src_event.source.default_location
        else:
            self.calDAV.icalendar_component["location"] = src_event.location

        self.calDAV.icalendar_component["categories"] = vCategory(src_event.combine_categories(src_event.source.tags))
        self.calDAV.icalendar_component["dtstart"] = icalDate(src_event.date_start)
        self.calDAV.icalendar_component["dtend"] = icalDate(src_event.date_end)
        # add/update last modified parameter cause nextcloud does not
        self.calDAV.icalendar_component["last-modified"] = icalDate(dt.datetime.now())

        self.calDAV.icalendar_component["status"] = src_event.status
        if (src_event.source.ignore_planned and src_event.is_planned) or src_event.is_confidential or src_event.is_excluded:
            # DELETE rather than save
            self.calDAV.delete()
            logger.success(f'Deleted {self.date} | {self.safe_title} out of the row in "{src_event.source.cal_name}".')
        else:
            self.calDAV.save()
        return self
