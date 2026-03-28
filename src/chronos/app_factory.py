# -*- coding: utf-8 -*-

"""
Created on 25.02.2022

@author: input
"""

# python lib
import datetime as dt
import json
import logging
import time
import zoneinfo

# external libs
from apscheduler.schedulers.background import BackgroundScheduler

# own code
from chronos.calendar_handlers.caldav_calendar_handler import CalDavCalendarHandler
from chronos.calendar_handlers.ics_calendar_handler import IcsCalendarHandler
from chronos.config import Config

logger = logging.getLogger(__name__)


class AppFactory:
    def __init__(self, app_config: Config):
        self.app_config = app_config
        target_calendar_timezone = self.app_config.get("app", "timezone")
        self.scheduler = BackgroundScheduler({"apscheduler.timezone": target_calendar_timezone})

        self.source_readable_calendars: list[IcsCalendarHandler] = []
        self.source_writable_calendars: list[CalDavCalendarHandler] = []
        self.target: CalDavCalendarHandler

        self.active = False

    def create(self) -> None:
        _td, _cd, _icons = self.read_cal_config()

        self.set_calendars(_td, _cd, _icons)

        logger.debug("Base elements created")

    def read_cal_config(self) -> tuple[dict, dict, dict]:
        fn_config = self.app_config.get("calendars", "file")
        with open(fn_config, "r", encoding="utf-8") as f:
            _data = json.load(f)
        return _data["target"], _data["calendars"], _data["icons"]

    def set_calendars(self, target_data: dict, calendars_data: dict, icons: dict) -> None:
        target_data["icons"] = icons
        self.target = CalDavCalendarHandler(self.app_config)
        self.target.config(target_data)

        for cal in calendars_data:
            cal["icons"] = icons
            calendar_adress = cal["cal_primary"]
            if ".ics" in calendar_adress or "?export" in calendar_adress:
                calendar_handler = IcsCalendarHandler(self.app_config)
                calendar_handler.config(cal)
                self.source_readable_calendars.append(calendar_handler)
            else:
                calendar_handler = CalDavCalendarHandler(self.app_config)
                calendar_handler.config(cal)
                self.source_writable_calendars.append(calendar_handler)

    def read_calendars(self) -> None:
        self.target.read()
        for calendar in self.source_readable_calendars:
            calendar.read()
        for calendar in self.source_writable_calendars:
            calendar.read()

    def sanitize_events(self) -> None:
        for calendar in self.source_writable_calendars:
            if not calendar.sanitize_stati and not calendar.sanitize_icons_src:
                continue

            for event in calendar.writable_events.values():
                if event.last_modified <= calendar.last_check:
                    continue

                do_save = False
                if calendar.sanitize_stati:
                    was_update_successful = calendar.sanitize_event_by_title(event)
                    do_save = do_save or was_update_successful
                if calendar.sanitize_icons_src:
                    was_title_change_succesful = event.set_title_icons()
                    do_save = do_save or was_title_change_succesful

                if do_save:
                    calendar.save_to_caldav(event)
                    logger.debug(f"Updated source event: {event.date} | {event.safe_title}")

    def init_schedulers(self) -> None:
        # appcron_value = f"*/{self.app_config.get('app', 'appcron')}"
        # self.scheduler.add_job(self.single_run, "cron", id="smallfish", hour=appcron_value, minute=0)

        datacron_value = str(self.app_config.get("app", "datacron"))
        self.scheduler.add_job(self.single_run, "cron", id="catfish", minute=datacron_value)

        self.scheduler.start()
        pass

    def run(self) -> None:
        self.active = True
        self.single_run()
        while self.active:
            time.sleep(60)

    def stop(self) -> None:
        self.active = False

    def single_run(self) -> None:
        try:
            self.read_calendars()
            logger.debug("Done parsing source calendars")
            self.sanitize_events()
            logger.debug("Cleaning up")
            self.sync_calendars()
            logger.debug("--== All done for this run ==--")
            self.close_calendars()
            logger.debug("Closed sockets to calendars")
        except Exception as ex:
            show_trace = self.app_config.get("log", "show_tracebacks")
            logger.critical(f"Cron excecution failed. Reason {ex}", exc_info=show_trace)

    def close_calendars(self):
        try:
            self.target.close_connection()
            all_calendars = self.source_readable_calendars + self.source_writable_calendars
            for calendar in all_calendars:
                calendar.close_connection()
        except Exception as ex:
            logger.critical(f"Closing sockets failed. Reason: {ex}")

    def sync_calendars(self) -> None:
        app_timezone = zoneinfo.ZoneInfo(self.app_config.get("app", "timezone"))
        show_trace = self.app_config.get("log", "show_tracebacks")
        all_calendars = self.source_readable_calendars + self.source_writable_calendars
        for calendar in all_calendars:
            changed, deleted, new = self.target.sync_calendar(calendar, show_trace)
            calendar.last_check = dt.datetime.now().astimezone(app_timezone)

            msg = f'Done comparing with "{calendar.cal_name}". '
            msg += f"{len(changed)} entries updated. "
            msg += f"{len(new)} entries added. "
            msg += f"{len(deleted)} entries deleted."
            logger.success(msg)
