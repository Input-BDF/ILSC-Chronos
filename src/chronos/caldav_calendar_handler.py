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


class CalDavCalendarHandler(BaseCalendarHandler):
    def __init__(self, app_config: Config):
        super().__init__(app_config)
