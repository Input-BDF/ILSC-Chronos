# python lib
from hashlib import md5
from string import Template
from typing import TYPE_CHECKING
import datetime as dt
import logging
import regex
import uuid

# external libs
from icalendar import vDDDTypes as icalDate
from icalendar.prop import vCategory
import caldav
import icalendar
import pytz

# own code
from chronos.core import helpers

if TYPE_CHECKING:
    from chronos.core.calendar_handler import CalendarHandler


logger = logging.getLogger(__name__)


class ChronosEvent:
    def __init__(self, source: "CalendarHandler"):
        self.source: "CalendarHandler" = source

        self.uid = uuid.uuid1()
        self.created: dt.datetime = dt.datetime.now()
        self.date: dt.date = None
        self.dt_start: dt.datetime = None
        self.dt_end: dt.datetime = None
        self.description: str = None
        self.location: str = None

        self.calDAV: caldav.Event | None = None
        self._ics_event: icalendar.Event | None = None

    def __repr__(self):
        return f"ChronosEvent - {self.date} | {self.title}"

    @property
    def has_title(self):
        "check if event has an empty title"
        return self.title != "N/A"

    @property
    def title(self):
        return self._clear_title(self.ical.get("summary")) if self.ical else "undefined"

    @property
    def safe_title(self):
        return regex.sub(r"[^\x00-\x7F]+", "", self.title)

    @property
    def ical(self) -> caldav.Event:
        if self.calDAV is not None:
            return self.calDAV.icalendar_component
        if self._ics_event is not None:
            return self._ics_event
        message = "neither self.calDAV.icalendar_component (for calendars from CalDAV input)"
        message += " nor self._ics_event (for calendars from ICS file input) is given"
        raise ValueError(message)

    @property
    def is_chronos_origin(self) -> bool:
        """check if chronos was creator of this event"""
        return self.origin == self.source.app_config.get("app", "app_id")

    @property
    def remote_changed(self) -> bool:
        """
        ' check if event was changed remotely in iCAL
        """
        _mod = self.ical.get("last-modified")
        return True if _mod else False

    @property
    def last_modified(self) -> dt.datetime:
        """return last modification date. if event never was modified the creation date is provided"""
        _mod = self.ical.get("last-modified")
        return _mod.dt if _mod else self.ical.get("dtstamp").dt

    @property
    def origin(self) -> str:
        """returns None if not set"""
        return self.ical.get("X-ILSC-ORIGIN")

    @property
    def cal_id(self) -> str:
        return self.ical.get("X-ILSC-CALID")

    @property
    def source_uid(self) -> str:
        """returns None if not set"""
        return self.ical.get("X-ILSC-UID")

    @property
    def prefixed_title(self) -> str:
        """return title prefixed with string defined in calender config"""
        if self.source.title_prefix and self.source.sanitize_icons_tgt:
            _prefix_format = self.source.app_config.get("calendars", "prefix_format")
            _pre = Template(_prefix_format).substitute(icons=self.icons, prefix=self.source.title_prefix).strip()
            return f"{_pre} | {self.title}"
        if self.source.title_prefix:
            return f"{self.source.title_prefix} | {self.title}"
        else:
            return self.title

    @property
    def categories(self) -> list:
        """fetch categories from ical object and return as list"""
        _cats = self.ical.get("categories")
        if _cats:
            _cats = _cats.to_ical().decode().split(",")
            return _cats
        return []

    @property
    def is_all_day(self):
        """
        check if event is set as allday event - no time given
        (assumption till now)
        """
        result = not (isinstance(self.dt_end, dt.datetime) and isinstance(self.dt_start, dt.datetime))
        return result

    @property
    def duration(self):
        """
        return event duration
        """
        return self.dt_end - self.dt_start

    @property
    def is_multiday(self):
        "check if event is multiday (more than 24h) event. 1-allday == 24h"
        return self.duration > dt.timedelta(hours=24)

    @property
    def is_planned(self) -> bool:
        """
        checks for ical status
            "TENTATIVE"           ;Indicates event is tentative.
            "CONFIRMED"           ;Indicates event is definite.
            "CANCELLED"           ;Indicates event is canceled
            returns True if satus is TENTATIVE
        """
        return True if (self.ical.get("status") == "TENTATIVE") or (self._is_planned_from_title) else False

    @property
    def _is_planned_from_title(self) -> bool:
        """
        true if title starts with ?
        """
        return self.title.startswith("?")

    @property
    def is_canceled(self) -> bool:
        """
        checks for ical status
            "TENTATIVE"           ;Indicates event is tentative.
            "CONFIRMED"           ;Indicates event is definite.
            "CANCELLED"           ;Indicates event is canceled
            returns True if satus is TENTATIVE
        """
        return True if self.ical.get("status") == "CANCELLED" else False

    @property
    def is_confidential(self) -> bool:
        class_content = self.ical.get("class")
        # "CLASS" entry being not set means that it is "PUBLIC" (as it is the default value)
        is_public = class_content is None or class_content == "PUBLIC"
        confidential = not is_public
        return confidential

    @property
    def is_excluded(self) -> bool:
        setEventCats = set(map(lambda x: x.lower(), self.categories))
        setExclude = set(map(lambda x: x.lower(), self.source.tags_excluded))
        do_exclude = not (setExclude.isdisjoint(setEventCats))
        return do_exclude

    @property
    def status(self):
        return self.ical.get("status")

    def _make_date(self, idate: icalDate, force_time: str):
        # allday:
        if self.is_all_day and self.is_multiday:
            return idate

        # affects only 24h allday events
        if self.is_all_day and not (self.is_multiday) and self.source.force_time:
            try:
                _time = dt.datetime.strptime(force_time, "%H:%M").time()
                app_timezone = pytz.timezone(self.source.app_config.get("app", "timezone"))
                combined_datetime = dt.datetime.combine(self.dt_start, _time)
                localized_combined_datetime = app_timezone.localize(combined_datetime)
                return localized_combined_datetime
            except ValueError as ve:
                raise ValueError(f"Incompatible time format given. Check %H:%M - {ve}")
            except Exception as ex:
                logger.critical(f"Can not read calendars forced time configuration - {ex}")
                raise

        # Pass original date
        return idate

    @property
    def date_start(self):
        result = self._make_date(self.dt_start, self.source.force_start)
        return result

    @property
    def date_end(self):
        result = self._make_date(self.dt_end, self.source.force_end)
        return result

    @property
    def date_out_of_range(self) -> bool:
        try:
            target = self._get_ical_start_date()
            today = dt.date.today()
            delta = (target - today).days
            range_max = self.source.app_config.get("calendars", "range_max")
            # Reduce by two days to bypass assumed day drift in Calendar selection
            out_of_range = delta > (range_max - 1)
            return out_of_range
        except Exception as ex:
            logger.critical(f"Could not determine day distance")
        return True

    @property
    def md5_string(self):
        return f"{self.date}_{self.safe_title}_{self.description}".encode("utf-8")

    @property
    def md5(self):
        return md5(self.md5_string).hexdigest()

    @property
    def key(self):
        if self.is_chronos_origin and self.source_uid:
            # return uid of original source calendar
            return self.source_uid.encode("utf-8")
        return f"{self.uid}".encode("utf-8")

    def populate_from_vcal_object(self) -> None:
        # TODO: ensure UID exists (at least it should )
        try:
            self.uid = str(self.ical.get("uid"))
            if self.is_confidential or self.is_excluded:
                logger.info(f"Skipping further ical parsing on confidential or excluded event: {self.uid} | Source: {self.source.cal_name}")
                return

            raw_dtstamp = self.ical.get("dtstamp")
            raw_dtstart = self.ical.get("dtstart")
            raw_dtend = self.ical.get("dtend")

            self.created = helpers.convert_to_date_or_utc_datetime(raw_dtstamp.dt)
            self.dt_start = helpers.convert_to_date_or_utc_datetime(raw_dtstart.dt)
            self.dt_end = helpers.convert_to_date_or_utc_datetime(raw_dtend.dt)

            self.date = self._get_ical_start_date()

            self.description = self.ical.get("description")
            self.location = self.ical.get("location")
        except Exception as ex:
            logger.error(f"Could not process Event UID: {self.uid} | Source: {self.source.cal_name} | Reason: - {ex}")
            raise ex

    def _get_ical_start_date(self) -> dt.date:
        _date = self.ical.get("dtstart").dt
        if isinstance(_date, dt.datetime):
            return _date.date()
        return _date

    def _clear_title(self, title: icalendar.vText) -> str:
        """
        Search for first occurance of any Prefix and replace
        Assumes that someone or thing added prefixes
        """
        # TODO: collect all possible prefixes and match against them
        if title:
            return regex.sub(r"^([^\|]*\|)", "", title.to_ical().decode(), count=0, flags=0).strip()
        return "N/A"

    def combine_categories(self, first: list) -> list:
        return first.copy() + list(set(self.categories) - set(first))

    def _rem_multline_comments(self, text: str) -> str:
        """Remove multiline comments"""
        _reg = r"(?:^\s*#{3}|(?<=\\n)\s*#{3})(?:\\n)?[^#]{3}.*?(?:#{3}\\n|#{3}$)"
        nocmt = regex.sub(_reg, "", text)
        return nocmt

    def _rem_singline_comments(self, text: str) -> str:
        """Remove single-line comments"""
        _reg = r"((?:^\s*#|(?<=\\n)\s*#).*?(?:[^\\]\\n|$))"
        nocmt = regex.sub(_reg, "", text)
        return nocmt

    def _strip_newlines(self, text: str) -> str:
        """reduce multiple newlines to max 2 remove strip leading/trailing newlines"""
        _reg = r"(^(?:\s*\\n){1,}|(?<=(?:\s*\\n){2})(?:\s*\\n)*)|((?:\s*\\n)*$)"
        nocmt = regex.sub(_reg, "", text)
        return nocmt

    def sanitize_description(self) -> icalendar.vText:
        try:
            _desc = self.description.to_ical().decode("utf-8")
        except:
            _desc = self.description.to_ical()
        nocmt = self._rem_multline_comments(_desc)
        nocmt = self._rem_singline_comments(nocmt)
        nocmt = self._strip_newlines(nocmt)
        return icalendar.vText(nocmt)

    def create_ical_event(self) -> icalendar.Event:
        new_event = icalendar.Event()

        app_timezone = pytz.timezone(self.source.app_config.get("app", "timezone"))
        _now = app_timezone.localize(dt.datetime.now())

        # set random uuid to support getting arround nextcloud deleting problem
        new_event.add("uid", uuid.uuid1())

        new_event.add("dtstamp", _now)
        new_event.add("dtstart", self.date_start)
        new_event.add("dtend", self.date_end)
        new_event.add("summary", self.prefixed_title)

        if self.source.ignore_descriptions == False and self.description:
            new_event.add("description", self.sanitize_description())

        if self.location == None:
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

        if src_event.source.ignore_descriptions == False and src_event.description:
            # add description to VEVENT
            if "description" not in self.calDAV.vobject_instance.vevent.contents.keys():
                self.calDAV.vobject_instance.vevent.add("description")
            self.calDAV.vobject_instance.vevent.description.value = src_event.sanitize_description()

        if src_event.location == None:
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
            for i in icons:
                icon_str += self.source.icons[i]
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

    def __eq__(self, other):
        if self.md5 == other.md5:
            return True
        else:
            logger.debug(f"Changed event found: {self.date} | {self.safe_title}")
            logger.debug(f"{self.source.cal_name}: {self.md5_string}")
            logger.debug(f"{self.md5}")
            logger.debug("vs:")
            logger.debug(f"{other.source.cal_name}: {other.md5_string}")
            logger.debug(f"{other.md5}")
            return False
