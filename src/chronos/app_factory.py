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
import icalendar
from apscheduler.schedulers.background import BackgroundScheduler

# own code
from chronos.calendar_handlers.base_calendar_handler import BaseCalendarHandler
from chronos.calendar_handlers.caldav_calendar_handler import CalDavCalendarHandler
from chronos.calendar_handlers.ics_calendar_handler import IcsCalendarHandler
from chronos.config import Config
from chronos.events.base_chronos_event import BaseChronosEvent

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
        all_calendars = self.source_readable_calendars + self.source_writable_calendars
        for calendar in all_calendars:
            changed, deleted, new = self.sync_calendar(calendar)
            calendar.last_check = dt.datetime.now().astimezone(app_timezone)

            msg = f'Done comparing with "{calendar.cal_name}". '
            msg += f"{len(changed)} entries updated. "
            msg += f"{len(new)} entries added. "
            msg += f"{len(deleted)} entries deleted."
            logger.success(msg)

    def sync_calendar(self, cal_handler: BaseCalendarHandler) -> tuple[dict, dict, dict]:
        # Update target calendar events from source calendar
        changed_events = self._update_target_events(cal_handler)
        # delete iCal event not in source calendar
        deleted_events = self._delete_target_events(cal_handler)
        # create iCal event only in source calendar
        new_events = self._create_target_events(cal_handler)

        return changed_events, deleted_events, new_events

    def _update_target_events(self, cal_handler: BaseCalendarHandler) -> dict:
        """Update existing target calendar events"""

        source_events = cal_handler.get_events_data()
        target_events = self.target.search_events_by_calid(cal_handler.chronos_id)
        change_set = set(target_events).intersection(set(source_events))
        changed = {}

        for event_id in change_set:
            target_event = target_events[event_id]
            source_event = source_events[event_id]

            # TODO: (Re)Implement respect remote changes
            # if source_event.last_modified > target_event.last_modified and not target_event.remote_changed:
            if source_event.last_modified > target_event.last_modified:
                try:
                    # updated_event = target_event.update_calDaV_event(source_event)
                    updated_event = cal_handler.update_remote_event(target_event, source_event)
                    changed[event_id] = updated_event

                    logger.info(f"Updated: {updated_event.date} | {updated_event.safe_title}")
                except Exception as ex:
                    logger.error(f"Could not update event: {ex}")

        return changed

    def _delete_target_events(self, cal_handler: BaseCalendarHandler) -> dict:
        """delete target iCal events that are not in source calendar (any more)"""

        wipe_on_target = self.app_config.get("calendars", "delete_on_target")
        if not wipe_on_target:
            return {}

        source_events = cal_handler.get_events_data()
        target_events = self.target.search_events_by_calid(cal_handler.chronos_id)
        delete_set = set(target_events).difference(set(source_events))
        deleted = {}

        for event_id in delete_set:
            try:
                if target_events[event_id].is_chronos_origin:
                    delete_event = target_events[event_id]
                    delete_event.calDAV.delete()
                    logger.info(f"Deleted: {delete_event.date} | {delete_event.safe_title}")
                    deleted[event_id] = delete_event
            except Exception as ex:
                logger.error(f"Could not delete obsolete event: {ex}")

        return deleted

    def _create_target_events(self, cal_handler: BaseCalendarHandler) -> dict:
        """create iCal events that are only in source calendar"""

        source_events = cal_handler.get_events_data()
        target_events = self.target.search_events_by_calid(cal_handler.chronos_id)
        new_set = set(source_events).difference(set(target_events))
        new_events: dict[icalendar.vText, BaseChronosEvent] = {}

        for event_id in new_set:
            new_event = source_events[event_id]
            if not (new_event.has_title):
                logger.debug(f"Ignoring event without title: {new_event.date}")
                continue
            if new_event.is_confidential:
                logger.debug(f"Ignoring confidential event: {new_event.date}")
                continue
            if new_event.is_excluded:
                logger.debug(f"Ignoring event excluded by tag: {new_event.date}")
                continue
            if (cal_handler.ignore_planned and new_event.is_planned) or new_event.is_canceled:
                logger.debug(f"Ignoring {new_event.status} event: {new_event.date} | {new_event.safe_title}")
                # skip planned events
                continue

            try:
                _cal = icalendar.Calendar()
                vevent = new_event.create_ical_event()

                _cal.add_component(vevent)
                _new = _cal.to_ical()
                self.target.calendar.add_event(_new, no_overwrite=True, no_create=False)
                logger.info(f"Created: {new_event.date} | {new_event.safe_title}")
                new_events[event_id] = new_event
            except Exception as ex:
                logger.error(f"Could not create new event: {ex}")
                if new_event is not None and hasattr(new_event, "title") and hasattr(new_event, "date"):
                    logger.error(f"Affected event: {new_event.safe_title} {new_event.date}")

        return new_events
