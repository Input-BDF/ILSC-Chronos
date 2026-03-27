# -*- coding: utf-8 -*-

# python lib
import datetime as dt
import logging

# external libs
import caldav
import icalendar
from icalendar import vDDDTypes as icalDate
from icalendar.prop import vCategory

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

    def update_calDaV_event(self, src_event):
        # DEPRECATED
        """update data from given event"""

        self.ical["summary"] = src_event.prefixed_title

        if src_event.description is None and "description" in self.calDAV.vobject_instance.vevent.contents.keys():
            # remove description from VEVENT cause it should not be there
            self.calDAV.vobject_instance.vevent.remove(self.calDAV.vobject_instance.vevent.description)

        if src_event.source.ignore_descriptions is False and src_event.description:
            # add description to VEVENT
            if "description" not in self.calDAV.vobject_instance.vevent.contents.keys():
                self.calDAV.vobject_instance.vevent.add("description")
            self.calDAV.vobject_instance.vevent.description.value = src_event.sanitize_description()

        if src_event.location is None:
            self.ical["location"] = src_event.source.default_location
        else:
            self.ical["location"] = src_event.location

        self.ical["categories"] = vCategory(src_event.combine_categories(src_event.source.tags))
        self.ical["dtstart"] = icalDate(src_event.date_start)
        self.ical["dtend"] = icalDate(src_event.date_end)
        # add/update last modified parameter cause nextcloud does not
        self.ical["last-modified"] = icalDate(dt.datetime.now())

        self.ical["status"] = src_event.status
        if (src_event.source.ignore_planned and src_event.is_planned) or src_event.is_confidential or src_event.is_excluded:
            # DELETE rather than save
            self.calDAV.delete()
            logger.success(f'Deleted {self.date} | {self.safe_title} out of the row in "{src_event.source.cal_name}".')
        else:
            self.calDAV.save()
        return self
