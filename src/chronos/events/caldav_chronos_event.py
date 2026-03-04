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

# typing workaround to prevent circular import (see https://docs.python.org/3/library/typing.html#typing.TYPE_CHECKING)
if TYPE_CHECKING:
    from chronos.events.base_chronos_event import BaseChronosEvent
    from chronos.calendar_handlers.base_calendar_handler import BaseCalendarHandler


logger = logging.getLogger(__name__)


class CalDavChronosEvent(BaseChronosEvent):
    def __init__(self, source: "BaseCalendarHandler", caldav_event: caldav.Event):
        super().__init__(source)

        self.calDAV: caldav.Event = caldav_event

    def __repr__(self):
        return f"CalDavChronosEvent - {self.date} | {self.title}"

    @property
    def ical(self) -> caldav.Event:
        return self.calDAV.icalendar_component

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

    def update_state_by_title(self):
        try:
            if self.title.startswith("?"):  # or self.title.endswith("?"):
                self.calDAV.icalendar_component["status"] = "TENTATIVE"
                self.calDAV.icalendar_component["summary"] = icalendar.vText(self.calDAV.icalendar_component["summary"].lstrip("?").strip())
                logger.success(f"Set correct visibility for {self.date} | {self.safe_title}")
                return True
        except Exception as ex:
            logger.error(f"Could not set correct visibility for {self.date} | {self.safe_title} - {ex}")

        return False

    def save(self):
        try:
            self.calDAV.save()
            self.calDAV.load()
            logger.success(f"Updated {self.date} | {self.safe_title}")
        except Exception as ex:
            logger.error(f"Could not update for {self.date} | {self.safe_title} - {ex}")
