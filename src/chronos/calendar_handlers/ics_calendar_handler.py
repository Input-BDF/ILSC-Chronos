# -*- coding: utf-8 -*-

# python lib
from hashlib import md5
from pathlib import Path
from urllib.request import urlretrieve
import datetime as dt
import logging
import time
import zoneinfo

# external libs
import caldav
import icalendar
import x_wr_timezone

# own code
from chronos.calendar_handlers.base_calendar_handler import BaseCalendarHandler
from chronos.config import Config
from chronos.chronos_event import ChronosEvent
from chronos.events.ics_chronos_event import IcsChronosEvent

logger = logging.getLogger(__name__)


class IcsCalendarHandler(BaseCalendarHandler):
    def __init__(self, app_config: Config):
        super().__init__(app_config)

        self.readonly_events: dict[str, IcsChronosEvent] = {}

    def get_events_data(self) -> dict[str, IcsChronosEvent]:
        return self.readonly_events

    def search_events_by_calid(self, calid: str) -> dict[str, IcsChronosEvent]:
        """search read events created by chronos with given calendar id"""
        found = {}
        for key, event in self.readonly_events.items():
            if calid == event.cal_id and event.is_chronos_origin:
                found[key] = event

        return found

    def read(self):
        """read events from .ics file from the calendars primary adress"""

        # reset data first
        self.readonly_events = {}

        # can't open ICS file directly, so first download
        pathname_tmp = Path("./tmp")
        pathname_tmp.mkdir(parents=True, exist_ok=True)
        fn_cal = pathname_tmp / f"tmp_{self.cal_name}.ics"
        urlretrieve(self.cal_primary, fn_cal)

        # TODO 2025-04-21 handle ICS file not being accessible

        with fn_cal.open(encoding="utf-8") as f:
            calendar_contents = f.read()
            ics_calendar = icalendar.Calendar.from_ical(calendar_contents)

        # safety check for correct calendar
        if str(ics_calendar["X-WR-CALNAME"]) != self.cal_name:
            logger.error(f"mismatch of calendar name ({ics_calendar['X-WR-CALNAME']=} vs {self.cal_name=})")
            return

        # use standardized format for timezone and find timezone
        standardized_icalendar = x_wr_timezone.to_standard(ics_calendar, add_timezone_component=True)
        timezone_id: str | None = None
        for subcomp in standardized_icalendar.walk("VTIMEZONE"):
            if timezone_id is not None:
                logger.error(f"multiple timezone instances in calendar '{self.cal_name}': '{timezone_id}' and '{subcomp.tz_name}'")
            timezone_id = subcomp.tz_name
        self.cal_timezone_info = zoneinfo.ZoneInfo(timezone_id)

        # compare with the time zone of the target calendar
        timezone_from_config = self.app_config.get("app", "timezone")
        target_timezone = zoneinfo.ZoneInfo(timezone_from_config)
        if target_timezone != self.cal_timezone_info:
            logger.warning(f"timezone of calendar ({self.cal_timezone_info}) is not the same as the target calendars timezone ({target_timezone})")

        for event in ics_calendar.walk("VEVENT"):
            new_chronos_event = IcsChronosEvent(self, event.copy())

            # Only handle public events and those not containing exclude tags
            is_invalid_event = new_chronos_event.is_confidential or new_chronos_event.is_excluded or new_chronos_event.date_out_of_range
            if is_invalid_event:
                logger.info(f"Skipping further ical parsing on confidential or excluded event: {new_chronos_event.uid} | Source: {self.cal_name}")
                continue

            new_chronos_event.populate_from_vcal_object()

            # TODO 2025-06-11 put into helper function for date range check
            # determine limits of time range with timezone info
            today_in_the_morning_utc = dt.datetime.today().replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=zoneinfo.ZoneInfo("UTC"))
            range_min = self.app_config.get("calendars", "range_min")
            limit_start_date = today_in_the_morning_utc + dt.timedelta(days=range_min)
            range_max = self.app_config.get("calendars", "range_max")
            limit_end_date = today_in_the_morning_utc + dt.timedelta(days=range_max)

            # handle different input types (dt.date or dt.datetime) with timezone info
            if isinstance(new_chronos_event.dt_start, dt.datetime):
                dt_start = new_chronos_event.dt_start
            else:
                dt_start = dt.datetime(
                    year=new_chronos_event.dt_start.year,
                    month=new_chronos_event.dt_start.month,
                    day=new_chronos_event.dt_start.day,
                    tzinfo=zoneinfo.ZoneInfo("UTC"),
                )

            if isinstance(new_chronos_event.dt_end, dt.datetime):
                dt_end = new_chronos_event.dt_end
            else:
                dt_end = dt.datetime(
                    year=new_chronos_event.dt_end.year,
                    month=new_chronos_event.dt_end.month,
                    day=new_chronos_event.dt_end.day,
                    tzinfo=zoneinfo.ZoneInfo("UTC"),
                )

            # check for limits
            if dt_start < limit_start_date:
                # print("event is in the past")
                continue

            if dt_end > limit_end_date:
                # print("event is in the far future")
                continue

            self.readonly_events[new_chronos_event.key] = new_chronos_event
