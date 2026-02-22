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
from chronos.config import Config
from chronos.chronos_event import ChronosEvent

import abc


logger = logging.getLogger(__name__)


class BaseCalendarHandler(abc.ABC):
    def __init__(self, app_config: Config):
        self.app_config = app_config

        app_timezone = zoneinfo.ZoneInfo(self.app_config.get("app", "timezone"))
        self.last_check = (dt.datetime.now() - dt.timedelta(days=7)).astimezone(app_timezone)
        self.cal_timezone_info = zoneinfo.ZoneInfo("UTC")

        self.events_data: dict[str, ChronosEvent] = {}

        self.client = None
        self.calendar = None
        self.principal = None

        # derived from calendars.json
        self.cal_primary = None
        self.cal_name = None
        self.cal_user = None
        self.cal_passwd = None

        self.force_time = False  # affects only 24h allday events
        self.force_start = None
        self.force_end = None

        self.ignore_planned = False
        self.ignore_descriptions = False
        self.title_prefix = None
        self.tags = []
        self.color = None
        self.default_location = None

        self.tags_excluded = []

        self.sanitize = {"stati": True, "source_icons": True, "target_icons": True}

        self.icons = {}

    @property
    def chronos_id(self) -> str:
        result = md5(f"{self.cal_name}_{self.cal_primary}".encode("utf-8")).hexdigest()
        return result

    def config(self, conf_data):
        for key, val in conf_data.items():
            if type(val) is dict:
                setattr(self, key, {**getattr(self, key), **val})
            else:
                setattr(self, key, val)

    @abc.abstractmethod
    def read(self) -> None:
        """abstract read calendar events method. use subclasses for reading ICS file or from a CalDAV calendar."""
        pass

    def search_events_by_calid(self, calid: str) -> dict[str, ChronosEvent]:
        """search read events created by chronos with given calendar id"""
        found = {}
        for key, event in self.events_data.items():
            if calid == event.cal_id and event.is_chronos_origin:
                found[key] = event

        return found

    def close_connection(self) -> None:
        pass
