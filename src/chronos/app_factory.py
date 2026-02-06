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
import icalendar

# own code
from chronos.config import Config
from chronos.calendar_handler import CalendarHandler
from chronos.chronos_event import ChronosEvent

logger = logging.getLogger(__name__)


class AppFactory:
    def __init__(self, app_config: Config):
        self.app_config = app_config
        target_calendar_timezone = self.app_config.get("app", "timezone")
        self.scheduler = BackgroundScheduler({"apscheduler.timezone": target_calendar_timezone})

        self.calendars: list[CalendarHandler] = []
        self.target: CalendarHandler

        self.active = False

    def create(self) -> None:
        _td, _cd, _icons = self.read_cal_config()

        self.set_calendars(_td, _cd, _icons)

        logger.debug("Base elements created")

    def read_cal_config(self) -> tuple[dict, dict, dict]:
        with open(self.app_config.get("calendars", "file"), "r", encoding="utf-8") as f:
            _data = json.load(f)
        return _data["target"], _data["calendars"], _data["icons"]

    def set_calendars(self, target_data: dict, calendars_data: dict, icons: dict) -> None:
        target_data["icons"] = icons
        self.target = CalendarHandler(self.app_config)
        self.target.config(target_data)

        for cal in calendars_data:
            cal["icons"] = icons
            _calendar = CalendarHandler(self.app_config)
            _calendar.config(cal)
            self.calendars.append(_calendar)

    def read_calendars(self) -> None:
        self.target.read()
        for calendar in self.calendars:
            calendar.read()

    def sanitize_events(self) -> None:
        for calendar in self.calendars:
            if calendar.sanitize_stati or calendar.sanitize_icons_src:
                for event in calendar.events_data.values():
                    if event.last_modified > calendar.last_check:
                        do_save = False
                        if calendar.sanitize_stati:
                            do_save = bool(do_save + event.update_state_by_title())
                        if calendar.sanitize_icons_src:
                            do_save = bool(do_save + event.set_title_icons())
                        if do_save:
                            event.save()
                            logger.debug(f"Updated source event: {event.date} | {event.safe_title}")

    def init_schedulers(self) -> None:
        appcron_value = f"*/{self.app_config.get('app', 'appcron')}"
        self.scheduler.add_job(self.cron_app, "cron", id="smallfish", hour=appcron_value, minute=0)

        datacron_value = str(self.app_config.get("app", "datacron"))
        self.scheduler.add_job(self.cron_app, "cron", id="catfish", minute=datacron_value)

        self.scheduler.start()
        pass

    def run(self) -> None:
        self.active = True
        self.cron_app()
        while self.active:
            time.sleep(60)

    def stop(self) -> None:
        self.active = False

    def cron_app(self) -> None:
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
            logger.critical(f"Cron excecution failed. Reason {ex}")

    def close_calendars(self):
        try:
            self.target.close_connection()
            for calendar in self.calendars:
                calendar.close_connection()
        except Exception as ex:
            logger.critical(f"Closing sockets failed. Reason: {ex}")

    def sync_calendars(self) -> None:
        app_timezone = zoneinfo.ZoneInfo(self.app_config.get("app", "timezone"))
        for calendar in self.calendars:
            changed, deleted, new = self.sync_calendar(calendar)
            calendar.last_check = dt.datetime.now().astimezone(app_timezone)

            msg = f'Done comparing with "{calendar.cal_name}". '
            msg += f"{len(changed)} entries updated. "
            msg += f"{len(new)} entries added. "
            msg += f"{len(deleted)} entries deleted."
            logger.success(msg)

    def sync_calendar(self, calendar: CalendarHandler) -> tuple[dict, dict, dict]:
        # Update target calendar events from source calendar
        changed = self._update_target_events(calendar)
        # delete iCal event not in source calendar
        deleted = self._delete_target_events(calendar)
        # create iCal event only in source calendar
        new = self._create_target_events(calendar)
        return changed, deleted, new

    def _update_target_events(self, calendar: CalendarHandler) -> dict:
        """Update target calendar events"""

        source_cal = calendar.events_data
        target_cal = self.target.search_events_by_calid(calendar.chronos_id)
        changeSet = set(target_cal).intersection(set(source_cal))
        changed = {}

        for event_id in changeSet:
            tgt = target_cal[event_id]
            src = source_cal[event_id]
            # TODO: (Re)Implement respect remote changes
            # if src.last_modified > tgt.last_modified and not tgt.remote_changed:
            if src.last_modified > tgt.last_modified:
                try:
                    updated_event = tgt.update_calDaV_event(src)
                    changed[event_id] = updated_event

                    logger.info(f"Updated: {updated_event.date} | {updated_event.safe_title}")
                except Exception as ex:
                    logger.error(f"Could not update event: {ex}")

        return changed

    def _delete_target_events(self, calendar: CalendarHandler) -> dict:
        """delete target iCal events not in source calendar"""

        wipe_on_target = self.app_config.get("calendars", "delete_on_target")
        if not wipe_on_target:
            return {}

        source_cal = calendar.events_data
        target_cal = self.target.search_events_by_calid(calendar.chronos_id)
        deleteSet = set(target_cal).difference(set(source_cal))
        deleted = {}

        for event_id in deleteSet:
            try:
                if target_cal[event_id].is_chronos_origin:
                    del_event = target_cal[event_id]
                    del_event.calDAV.delete()
                    logger.info(f"Deleted: {del_event.date} | {del_event.safe_title}")
                    deleted[event_id] = del_event
            except Exception as ex:
                logger.error(f"Could not delete obsolete event: {ex}")

        return deleted

    def _create_target_events(self, calendar: CalendarHandler) -> dict:
        """create iCal events only in source calendar"""
        source_cal = calendar.events_data
        target_cal = self.target.search_events_by_calid(calendar.chronos_id)
        newSet = set(source_cal).difference(set(target_cal))
        new_events: dict[icalendar.vText, ChronosEvent] = {}

        for event_id in newSet:
            new_event = source_cal[event_id]
            if not (new_event.has_title):
                logger.debug(f"Ignoring event without title: {new_event.date}")
                continue
            if new_event.is_confidential:
                logger.debug(f"Ignoring confidential event: {new_event.date}")
                continue
            if new_event.is_excluded:
                logger.debug(f"Ignoring event excluded by tag: {new_event.date}")
                continue
            if (calendar.ignore_planned and new_event.is_planned) or new_event.is_canceled:
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
