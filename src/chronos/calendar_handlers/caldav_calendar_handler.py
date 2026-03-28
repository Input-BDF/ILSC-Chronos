# -*- coding: utf-8 -*-

# python lib
import datetime as dt
import logging
import time
import zoneinfo

# external libs
import caldav
import caldav.collection
import caldav.davclient
import icalendar
from icalendar import vDDDTypes as icalDate
from icalendar.prop import vCategory

# own code
from chronos.calendar_handlers.base_calendar_handler import BaseCalendarHandler
from chronos.config import Config
from chronos.events.base_chronos_event import BaseChronosEvent
from chronos.events.caldav_chronos_event import CalDavChronosEvent

logger = logging.getLogger(__name__)


class CalDavCalendarHandler(BaseCalendarHandler):
    def __init__(self, app_config: Config):
        super().__init__(app_config)

        self.client: caldav.davclient.DAVClient
        self.calendar: caldav.collection.Calendar
        self.principal: caldav.davclient.Principal

        self.writable_events: dict[str, CalDavChronosEvent] = {}

    def get_events_data(self) -> dict[str, CalDavChronosEvent]:
        return self.writable_events

    @property
    def sanitize_stati(self) -> bool:
        return self.sanitize["stati"]

    @property
    def sanitize_icons_src(self) -> bool:
        return self.sanitize["source_icons"]

    @property
    def sanitize_icons_tgt(self) -> bool:
        return self.sanitize["target_icons"]

    def available_calendars(self) -> list[caldav.collection.Calendar]:
        calendars = self.principal.calendars()
        logger.info(f"Fetching available calendars on: {self.cal_name}")
        logger.debug("Found:")

        for calendar in calendars:
            logger.debug(f"\t{calendar.name}")

        return calendars

    def search_events_by_calid(self, calid: str) -> dict[str, CalDavChronosEvent]:
        """search read events created by chronos with given calendar id"""
        found = {}
        for key, event in self.writable_events.items():
            if calid == event.cal_id and event.is_chronos_origin:
                found[key] = event

        return found

    def read(self) -> None:
        """read events from caldav calendar"""
        logger.debug(f'Connecting Calendar "{self.cal_name}"')

        start = time.time()
        try:
            self.client = caldav.davclient.DAVClient(
                url=self.cal_primary,
                username=self.cal_user,
                password=self.cal_passwd,
            )
            self.principal = self.client.get_principal()
        except Exception as ex:
            logger.critical(f"Error on CALDav auth: {ex}")
            raise

        self.writable_events = {}

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
        # dates = [value.key for (key, value) in sorted(self.writable_events.items(), reverse=False)]
        logger.debug("Time needed: {:.2f}s".format(time.time() - start))

        if self.calendar is None:
            raise ValueError(f"read_from_cal_dav: target calendar '{self.cal_name}' was not found!")

    def read_event(self, calEvent: caldav.collection.Event) -> None:
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
                chronos_event = CalDavChronosEvent(self, calEvent)

                # Only handle public events and those not conataining exclude tags
                is_invalid_event = chronos_event.is_confidential or chronos_event.is_excluded or chronos_event.date_out_of_range
                if is_invalid_event:
                    logger.info(f"Skipping confidential or excluded event: {chronos_event.uid} | Source: {self.cal_name} | {chronos_event.safe_title}")
                    continue

                chronos_event.populate_from_vcal_object()
                self.writable_events[chronos_event.key] = chronos_event

    def save_to_caldav(self, caldav_event: CalDavChronosEvent):
        try:
            caldav_event.calDAV.save()
            caldav_event.calDAV.load()
            logger.success(f"Updated {caldav_event.date} | {caldav_event.safe_title}")
        except Exception as ex:
            logger.error(f"Could not update for {caldav_event.date} | {caldav_event.safe_title} - {ex}")

    def update_remote_event(self, target_event: CalDavChronosEvent, source_event: BaseChronosEvent):
        """update data from given event"""

        target_event.ical["summary"] = source_event.prefixed_title

        if source_event.description is None and "description" in target_event.calDAV.vobject_instance.vevent.contents.keys():
            # remove description from VEVENT cause it should not be there
            target_event.calDAV.vobject_instance.vevent.remove(target_event.calDAV.vobject_instance.vevent.description)

        if source_event.source.ignore_descriptions is False and source_event.description:
            # add description to VEVENT
            if "description" not in target_event.calDAV.vobject_instance.vevent.contents.keys():
                target_event.calDAV.vobject_instance.vevent.add("description")
            target_event.calDAV.vobject_instance.vevent.description.value = source_event.sanitize_description()

        if source_event.location is None:
            target_event.ical["location"] = source_event.source.default_location
        else:
            target_event.ical["location"] = source_event.location

        target_event.ical["categories"] = vCategory(source_event.combine_categories(source_event.source.tags))
        target_event.ical["dtstart"] = icalDate(source_event.date_start)
        target_event.ical["dtend"] = icalDate(source_event.date_end)
        # add/update last modified parameter cause nextcloud does not
        target_event.ical["last-modified"] = icalDate(dt.datetime.now())

        target_event.ical["status"] = source_event.status
        if (source_event.source.ignore_planned and source_event.is_planned) or source_event.is_confidential or source_event.is_excluded:
            # DELETE rather than save
            target_event.calDAV.delete()
            logger.success(f'Deleted {target_event.date} | {target_event.safe_title} out of the row in "{source_event.source.cal_name}".')
        else:
            target_event.calDAV.save()
        return target_event

    def close_connection(self) -> None:
        if self.client is not None:
            self.client.close()

    def sync_calendar(self, cal_handler: BaseCalendarHandler, show_trace: bool) -> tuple[dict, dict, dict]:
        # Update target calendar events from source calendar
        changed_events = self._update_target_events(cal_handler, show_trace)
        # delete iCal event not in source calendar
        deleted_events = self._delete_target_events(cal_handler, show_trace)
        # create iCal event only in source calendar
        new_events = self._create_target_events(cal_handler, show_trace)

        return changed_events, deleted_events, new_events

    def _update_target_events(self, cal_handler: BaseCalendarHandler, show_trace: bool) -> dict:
        """Update existing target calendar events"""

        source_events = cal_handler.get_events_data()
        target_events = self.search_events_by_calid(cal_handler.chronos_id)
        change_set = set(target_events).intersection(set(source_events))
        changed: dict[str, BaseChronosEvent] = {}

        for event_id in change_set:
            target_event = target_events[event_id]
            source_event = source_events[event_id]

            # TODO: (Re)Implement respect remote changes
            # if source_event.last_modified > target_event.last_modified and not target_event.remote_changed:
            if source_event.last_modified > target_event.last_modified:
                try:
                    # updated_event = target_event.update_calDaV_event(source_event)
                    updated_event = self.update_remote_event(target_event, source_event)
                    changed[event_id] = updated_event

                    logger.info(f"Updated: {updated_event.date} | {updated_event.safe_title}")
                except Exception as ex:
                    logger.error(f"Could not update event: {ex}", exc_info=show_trace)

        return changed

    def _delete_target_events(self, cal_handler: BaseCalendarHandler, show_trace: bool) -> dict:
        """delete target iCal events that are not in source calendar (any more)"""

        wipe_on_target = self.app_config.get("calendars", "delete_on_target")
        if not wipe_on_target:
            return {}

        source_events = cal_handler.get_events_data()
        target_events = self.search_events_by_calid(cal_handler.chronos_id)
        delete_set = set(target_events).difference(set(source_events))
        deleted: dict[str, BaseChronosEvent] = {}

        for event_id in delete_set:
            try:
                if target_events[event_id].is_chronos_origin:
                    delete_event = target_events[event_id]
                    delete_event.calDAV.delete()
                    logger.info(f"Deleted: {delete_event.date} | {delete_event.safe_title}")
                    deleted[event_id] = delete_event
            except Exception as ex:
                logger.error(f"Could not delete obsolete event: {ex}", exc_info=show_trace)

        return deleted

    def _create_target_events(self, cal_handler: BaseCalendarHandler, show_trace: bool) -> dict:
        """create iCal events that are only in source calendar"""

        source_events = cal_handler.get_events_data()
        target_events = self.search_events_by_calid(cal_handler.chronos_id)
        new_set = set(source_events).difference(set(target_events))
        new_events: dict[str, BaseChronosEvent] = {}

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
                tmp_cal = icalendar.Calendar()
                vevent: icalendar.Event = new_event.create_ical_event()

                tmp_cal.add_component(vevent)
                new_ical_raw_text: bytes = tmp_cal.to_ical()
                self.calendar.add_event(new_ical_raw_text, no_overwrite=True, no_create=False)
                logger.info(f"Created: {new_event.date} | {new_event.safe_title}")
                new_events[event_id] = new_event
            except Exception as ex:
                logger.error(f"Could not create new event: {ex}", exc_info=show_trace)
                if new_event is not None and hasattr(new_event, "title") and hasattr(new_event, "date"):
                    logger.error(f"Affected event: {new_event.safe_title} {new_event.date}")

        return new_events
