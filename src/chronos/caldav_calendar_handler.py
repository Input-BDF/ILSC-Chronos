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
from chronos.base_calendar_handler import BaseCalendarHandler
from chronos.config import Config
from chronos.chronos_event import ChronosEvent

logger = logging.getLogger(__name__)


class CalDavCalendarHandler(BaseCalendarHandler):
    def __init__(self, app_config: Config):
        super().__init__(app_config)

    @property
    def sanitize_stati(self) -> bool:
        return self.sanitize["stati"]

    @property
    def sanitize_icons_src(self) -> bool:
        return self.sanitize["source_icons"]

    @property
    def sanitize_icons_tgt(self) -> bool:
        return self.sanitize["target_icons"]

    def available_calendars(self) -> list[caldav.Calendar]:
        calendars = self.principal.calendars()
        logger.info(f"Fetching available calendars on: {self.cal_name}")
        logger.debug("Found:")

        for calendar in calendars:
            logger.debug(f"\t{calendar.name}")

        return calendars

    def read(self) -> None:
        """read events from caldav calendar"""
        logger.debug(f'Connecting Calendar "{self.cal_name}"')

        start = time.time()
        try:
            self.client = caldav.DAVClient(self.cal_primary, username=self.cal_user, password=self.cal_passwd)
            self.principal = self.client.principal()
        except Exception as ex:
            logger.critical(f"Error on CALDav auth: {ex}")
            raise

        self.events_data = {}

        logger.debug("Time needed: {:.2f}s".format(time.time() - start))
        start = time.time()

        logger.debug("Reading Events")
        list_available_calendars = self.available_calendars()
        for calendar in list_available_calendars:
            if calendar.name != self.cal_name:
                continue

            self.calendar = calendar
            # TODO: Check if timezone or utc converion is needed
            # had to add 2 hours else duplicates are created
            today_in_the_morning_utc = dt.datetime.today().replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=zoneinfo.ZoneInfo("UTC"))
            range_min = self.app_config.get("calendars", "range_min")
            limit_start_date = today_in_the_morning_utc + dt.timedelta(days=range_min)
            range_max = self.app_config.get("calendars", "range_max")
            limit_end_date = today_in_the_morning_utc + dt.timedelta(days=range_max)

            logger.debug(f'Checking calendar "{self.cal_name}" for dates in range: {limit_start_date} to {limit_end_date}')

            try:
                upcoming_events = calendar.search(
                    start=limit_start_date,
                    end=limit_end_date,
                    event=True,
                    expand=True,
                )
            except Exception:
                # print("Your calendar server does apparently not support expanded search")
                upcoming_events = calendar.search(
                    start=limit_start_date,
                    end=limit_end_date,
                    event=True,
                    expand=False,
                )

            # get all events
            for event in upcoming_events:
                if event.data:
                    try:
                        self.read_event(event)
                    except Exception as ex:
                        logger.error(f"Error reading event: {ex}")

        # uncomment as helper to check fetched events sorted by sektion and dates
        # dates = [value.key for (key, value) in sorted(self.events_data.items(), reverse=False)]
        logger.debug("Time needed: {:.2f}s".format(time.time() - start))

        if self.calendar is None:
            raise ValueError(f"read_from_cal_dav: target calendar '{self.cal_name}' was not found!")

    def read_event(self, calEvent: caldav.Event) -> None:
        """read event data"""
        # TODO: Clean this mess. As there should only be one vevent component. at least if caldav filter is working
        cal = icalendar.Calendar.from_ical(calEvent.data)
        components = cal.walk("vevent")
        # logger.debug(f'Nr of vevent components {len(components)}')
        for component in components:
            if component.name == "VEVENT":
                """
                #only needed if parsing all events in calendar
                #TODO: check what this was for ^^
                edate = component.get('dtstart').dt
                if isinstance(edate, datetime):
                    edate = edate.date()
                #if edate >= date.start_date():
                """
                chronos_event = ChronosEvent(self)
                chronos_event.calDAV = calEvent

                # Only handle public events and those not conataining exclude tags
                if not chronos_event.is_confidential and not chronos_event.is_excluded and not chronos_event.date_out_of_range:
                    chronos_event.populate_from_vcal_object()
                    self.events_data[chronos_event.key] = chronos_event

    def close_connection(self) -> None:
        if self.client is not None:
            self.client.close()
