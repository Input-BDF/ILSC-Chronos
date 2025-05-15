# -*- coding: utf-8 -*-
'''
Created on 25.02.2022

@author: input
'''

# python lib
from hashlib import md5
from pathlib import Path
from string import Template
from urllib.request import urlretrieve
import datetime as dt
import json
import regex
import time
import uuid

# external libs
from apscheduler.schedulers.background import BackgroundScheduler
from icalendar import Calendar, Event as icalEvent, vDDDTypes as icalDate, vText
from icalendar.prop import vCategory
import caldav
import icalendar
import pytz

# own code
from __main__ import appConfig
from core.log_factory import get_app_logger

logger = get_app_logger()

TimeZone = pytz.timezone(appConfig.get('app','timezone'))

APP_ID = appConfig.get('app', 'app_id')
RANGE_MIN = appConfig.get('calendars', 'range_min')
RANGE_MAX = appConfig.get('calendars', 'range_max')
WIPE_ON_TARGET = appConfig.get('calendars', 'delete_on_target')

def convert_to_date_or_timezone_datetime(date_time: dt.datetime, time_zone: str) -> dt.date | dt.datetime:
    '''
    convert to given timezone
    '''
    if isinstance(date_time, dt.datetime):
        result = pytz.timezone(time_zone).normalize(date_time)
    elif isinstance(date_time, dt.date):
        result = date_time
    else:
        raise ValueError(f"argument type ({type(date_time)}) not supported")
    return result

def convert_to_date_or_utc_datetime(date_or_datetime: dt.date | dt.datetime) -> dt.date | dt.datetime:
    if isinstance(date_or_datetime, dt.datetime):
        result = date_or_datetime.astimezone(dt.UTC)
    elif isinstance(date_or_datetime, dt.date):
        result = date_or_datetime
    else:
        raise ValueError(f"argument type ({type(date_or_datetime)}) not supported")
    return result


class ILSCEvent:
    
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
        return f"ILSCEvent - {self.date} | {self.title}"
    
    @property
    def has_title(self):
        'check if event has an empty title '
        return self.title != 'N/A'
    
    @property
    def title(self):
        return self._clear_title(self.ical.get('summary')) if self.ical else 'undefined'
    
    @property
    def safe_title(self):
        return regex.sub(r'[^\x00-\x7F]+','', self.title)
    
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
        ''' check if chronos was creator of this event '''
        return self.origin == APP_ID
    
    @property
    def remote_changed(self) -> bool:
        '''
        ' check if event was changed remotely in iCAL
        '''
        _mod = self.ical.get('last-modified')
        return True if _mod else False  
    
    @property
    def last_modified(self) -> dt.datetime:
        '''return last modification date. if event never was modified the creation date is provided'''
        _mod = self.ical.get('last-modified')
        return _mod.dt if _mod else self.ical.get('dtstamp').dt
    
    @property
    def origin(self) -> str:
        '''returns None if not set'''
        return self.ical.get('X-ILSC-ORIGIN')
    
    @property
    def cal_id(self) -> str:
        return self.ical.get('X-ILSC-CALID')
    
    @property
    def source_uid(self) -> str:
        '''returns None if not set'''
        return self.ical.get('X-ILSC-UID')
    
    @property
    def prefixed_title(self) -> str:
        '''return title prefixed with string defined in calender config'''
        if self.source.title_prefix and self.source.sanitize_icons_tgt: 
            _pre = Template(appConfig.get('calendars','prefix_format')).substitute(icons = self.icons, prefix = self.source.title_prefix).strip()
            return f"{_pre} | {self.title}"
        if self.source.title_prefix:
            return f"{self.source.title_prefix} | {self.title}"
        else:
            return self.title 
    
    @property
    def categories(self) -> list:
        '''fetch categories from ical object and return as list'''
        _cats = self.ical.get('categories')
        if _cats:
            _cats = _cats.to_ical().decode().split(',')
            return _cats
        return []
    
    @property
    def is_all_day(self):
        '''
        check if event is set as allday event - no time given
        (assumption till now)
        '''
        result = not( isinstance(self.dt_end, dt.datetime) and isinstance(self.dt_start, dt.datetime) )
        return result
    
    @property
    def duration(self):
        '''
        return event duration
        '''
        return self.dt_end - self.dt_start 
    
    @property
    def is_multiday(self):
        'check if event is multiday (more than 24h) event. 1-allday == 24h'
        return self.duration > dt.timedelta(hours = 24)
    
    @property
    def is_planned(self) -> bool:
        '''
        checks for ical status
            "TENTATIVE"           ;Indicates event is tentative.
            "CONFIRMED"           ;Indicates event is definite.
            "CANCELLED"           ;Indicates event is canceled
            returns True if satus is TENTATIVE
        '''
        return True if ( self.ical.get('status') == "TENTATIVE" ) or ( self._is_planned_from_title ) else False
    
    @property
    def _is_planned_from_title(self) -> bool:
        '''
        true if title starts with ?
        '''
        return self.title.startswith("?")
    
    @property
    def is_canceled(self) -> bool:
        '''
        checks for ical status
            "TENTATIVE"           ;Indicates event is tentative.
            "CONFIRMED"           ;Indicates event is definite.
            "CANCELLED"           ;Indicates event is canceled
            returns True if satus is TENTATIVE
        '''
        return True if self.ical.get('status') == "CANCELLED" else False
    
    @property
    def is_confidential(self) -> bool:
        class_content = self.ical.get('class')
        # "CLASS" entry being not set means that it is "PUBLIC" (as it is the default value)
        is_public = class_content is None or class_content == "PUBLIC"
        confidential = not is_public
        return confidential
    
    @property
    def is_excluded(self) -> bool:
        setEventCats = set(map(lambda x:x.lower(), self.categories))
        setExclude = set(map(lambda x:x.lower(), self.source.tags_excluded))
        do_exclude = not(setExclude.isdisjoint(setEventCats))
        return do_exclude
    
    @property
    def status(self):
        return self.ical.get('status')
    
    def _make_date(self, idate: icalDate, force_time: str):
        #allday:
        if self.is_all_day and self.is_multiday:
            return idate

        #affects only 24h allday events
        if self.is_all_day and not(self.is_multiday) and self.source.force_time:
            try:
                _time = dt.datetime.strptime(force_time, '%H:%M').time()
                return TimeZone.localize(dt.datetime.combine(self.dt_start, _time))
            except ValueError as ve:
                raise ValueError(f'Incompatible time format given. Check %H:%M - {ve}')
            except Exception as ex:
                logger.critical(f'Can not read calendars forced time configuration - {ex}')
                raise

        #Pass original date
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
            out_of_range = delta > ( RANGE_MAX - 1 )  # Reduce by two days to bypass assumed day drift in Calendar selection
            return out_of_range 
        except Exception as ex:
            logger.critical(f'Could not determine day distance')
        return True
    
    @property
    def md5_string(self):
        return f'{self.date}_{self.safe_title}_{self.description}'.encode('utf-8')
    
    @property
    def md5(self):
        return md5(self.md5_string).hexdigest()
    
    @property
    def key(self):
        if self.is_chronos_origin and self.source_uid:
            #return uid of original source calendar
            return self.source_uid.encode('utf-8')
        return f'{self.uid}'.encode('utf-8')

    def populate_from_vcal_object(self) -> None:
        #TODO: ensure UID exists (at least it should )
        try:
            self.uid = str(self.ical.get('uid'))
            if self.is_confidential or self.is_excluded:
                logger.info(f"Skipping further ical parsing on confidential or excluded event: {self.uid} | Source: {self.source.cal_name}")
                return
            
            raw_dtstamp = self.ical.get('dtstamp')
            raw_dtstart = self.ical.get('dtstart')
            raw_dtend = self.ical.get('dtend')

            self.created = convert_to_date_or_utc_datetime(raw_dtstamp.dt)
            self.dt_start = convert_to_date_or_utc_datetime(raw_dtstart.dt)
            self.dt_end = convert_to_date_or_utc_datetime(raw_dtend.dt)
            
            self.date = self._get_ical_start_date()
            
            self.description = self.ical.get('description')
            self.location = self.ical.get('location')
        except Exception as ex:
            logger.error(f"Could not process Event UID: {self.uid} | Source: {self.source.cal_name} | Reason: - {ex}")
            raise ex

    def _get_ical_start_date(self) -> dt.date:
        _date = self.ical.get('dtstart').dt
        if isinstance(_date, dt.datetime):
            return _date.date()
        return _date

    def _clear_title(self, title: vText) -> str:
        '''
        Search for first occurance of any Prefix and replace
        Assumes that someone or thing added prefixes
        '''
        #TODO: collect all possible prefixes and match against them
        if title:
            return regex.sub(r"^([^\|]*\|)", "", title.to_ical().decode(), count=0, flags=0).strip()
        return 'N/A'
    
    def combine_categories(self, first: list) -> list:
        return first.copy() + list(set(self.categories) - set(first))
    
    def _rem_multline_comments(self, text:str) -> str:
        '''Remove multiline comments'''
        _reg = r"(?:^\s*#{3}|(?<=\\n)\s*#{3})(?:\\n)?[^#]{3}.*?(?:#{3}\\n|#{3}$)"
        nocmt = regex.sub(_reg,'', text)
        return nocmt
    
    def _rem_singline_comments(self, text:str) -> str:
        '''Remove single-line comments'''
        _reg = r"((?:^\s*#|(?<=\\n)\s*#).*?(?:[^\\]\\n|$))"
        nocmt = regex.sub(_reg,'', text)
        return nocmt

    def _strip_newlines(self, text:str) -> str:
        '''reduce multiple newlines to max 2 remove strip leading/trailing newlines'''
        _reg = r"(^(?:\s*\\n){1,}|(?<=(?:\s*\\n){2})(?:\s*\\n)*)|((?:\s*\\n)*$)"
        nocmt = regex.sub(_reg,'', text)
        return nocmt
    
    def sanitize_description(self) -> vText:
        try:
            _desc = self.description.to_ical().decode('utf-8')
        except:
            _desc = self.description.to_ical()
        nocmt = self._rem_multline_comments(_desc)
        nocmt = self._rem_singline_comments(nocmt)
        nocmt = self._strip_newlines(nocmt)
        return icalendar.vText(nocmt)
    
    def create_ical_event(self) -> icalEvent:
        new_event=icalEvent()
        _now = TimeZone.localize(dt.datetime.now())

        #set random uuid to support getting arround nextcloud deleting problem
        new_event.add('uid', uuid.uuid1())
        
        new_event.add('dtstamp', _now)
        new_event.add('dtstart', self.date_start)
        new_event.add('dtend', self.date_end)
        new_event.add('summary', self.prefixed_title)
        
        if self.source.ignore_descriptions == False and self.description:
            new_event.add('description', self.sanitize_description())

        if self.location == None:
            new_event.add('location', self.source.default_location)
        else:
            new_event.add('location', self.location)

        new_event.add('categories', self.combine_categories(self.source.tags))
        new_event.add('status', self.status)
        
        if self.source.color:
            new_event.add('color', self.source.color)

        ####
        #CUSTOM PROPERTIES
        #TODO: Check existence after updating with HIDs (works on rainlendar, android phone [google calendar, jorte] 
        new_event.add('X-ILSC-ORIGIN', APP_ID)
        new_event.add('X-ILSC-CREATED', str(_now))
        new_event.add('X-ILSC-CALID', self.source.chronos_id)
        new_event.add('X-ILSC-UID', self.key)
            
        return new_event
    
    def update_calDaV_event(self, src_event):
        '''update data from given event'''
        
        self.calDAV.icalendar_component['summary'] = src_event.prefixed_title
        
        if src_event.description is None and 'description' in self.calDAV.vobject_instance.vevent.contents.keys():
            #remove description from VEVENT cause it should not be there
            self.calDAV.vobject_instance.vevent.remove(self.calDAV.vobject_instance.vevent.description)
        
        if src_event.source.ignore_descriptions == False and src_event.description:
            #add description to VEVENT
            if 'description' not in self.calDAV.vobject_instance.vevent.contents.keys():
                self.calDAV.vobject_instance.vevent.add('description')
            self.calDAV.vobject_instance.vevent.description.value = src_event.sanitize_description()
        
        if src_event.location == None:
            self.calDAV.icalendar_component['location'] = src_event.source.default_location
        else:
            self.calDAV.icalendar_component['location'] = src_event.location
        
        self.calDAV.icalendar_component['categories'] = vCategory(src_event.combine_categories(src_event.source.tags))
        self.calDAV.icalendar_component['dtstart'] = icalDate(src_event.date_start)
        self.calDAV.icalendar_component['dtend'] = icalDate(src_event.date_end)
        #add/update last modified parameter cause nextcloud does not
        self.calDAV.icalendar_component['last-modified'] = icalDate(dt.datetime.now())
        
        self.calDAV.icalendar_component['status'] = src_event.status
        if ( src_event.source.ignore_planned and src_event.is_planned ) or src_event.is_confidential or src_event.is_excluded:
            #DELETE rather than save
            self.calDAV.delete()
            logger.success(f'Deleted {self.date} | {self.safe_title} out of the row in "{src_event.source.cal_name}".')
        else:
            self.calDAV.save()
        return self
    
    def set_title_icons(self, sep = ' | '):
        try:
            if self.icons:
                _new_title = icalendar.vText(f"{self.icons}{sep}{self.title}")
                self.calDAV.icalendar_component['summary'] = _new_title
                logger.success(f"Event icons set for {self.date} | {self.safe_title}")
                return True
            #return False
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
            if self.title.startswith("?"):# or self.title.endswith("?"):
                self.calDAV.icalendar_component['status'] = 'TENTATIVE'
                self.calDAV.icalendar_component['summary'] = icalendar.vText(self.calDAV.icalendar_component['summary'].lstrip("?").strip())
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
            logger.debug(f'Changed event found: {self.date} | {self.safe_title}')
            logger.debug(f'{self.source.cal_name}: {self.md5_string}')
            logger.debug(f'{self.md5}')
            logger.debug('vs:')
            logger.debug(f'{other.source.cal_name}: {other.md5_string}')
            logger.debug(f'{other.md5}')
            return False

class CalendarHandler:
    
    def __init__(self):
        self.last_check = TimeZone.localize(dt.datetime.now() - dt.timedelta(days = 7))
        
        self.events_data: dict[str, ILSCEvent] = {}
        
        self.client = None
        self.calendar = None
        self.principal = None
        
        #derived from calendars.json
        self.cal_primary = None
        self.cal_name = None
        self.cal_user = None
        self.cal_passwd = None
        
        self.force_time = False #affects only 24h allday events
        self.force_start = None
        self.force_end = None

        self.ignore_planned = False
        self.ignore_descriptions = False
        self.title_prefix = None
        self.tags = []
        self.color = None
        self.default_location = None
        
        self.tags_excluded = []
        
        self.sanitize = {
                "stati" : True,
                "source_icons" : True,
                "target_icons" : True
        }
        
        self.icons = {}
    
    @property
    def chronos_id(self) -> str:
        result = md5(f'{self.cal_name}_{self.cal_primary}'.encode('utf-8')).hexdigest()
        return result
    
    @property
    def sanitize_stati(self) -> bool:
        return self.sanitize["stati"]
    
    @property
    def sanitize_icons_src(self) -> bool:
        return self.sanitize["source_icons"]

    @property
    def sanitize_icons_tgt(self) -> bool:
        return self.sanitize["target_icons"]

    def config(self, conf_data):
        for key, val in conf_data.items():
            if type(val) == dict:
                #setattr(self, key, getattr(self, key) | val)
                setattr(self, key, {**getattr(self, key), **val})
            else:
                setattr(self, key, val)

    
    def read(self) -> None:
        ''' read calendar events. decides if it is from a ICS file or from a CalDAV calendar. '''

        if ".ics" in self.cal_primary:
            self.read_ics_from_url()
        else:
            self.read_from_cal_dav()
    
    def read_ics_from_url(self):
        ''' read events form .ics file from a calendars primary adress '''

        # can't open ICS file directly, so first download
        pathname_tmp = Path("./tmp")
        pathname_tmp.mkdir(parents=True, exist_ok=True)
        fn_cal = pathname_tmp / f"tmp_{self.cal_name}.ics"
        urlretrieve(self.cal_primary, fn_cal)

        # TODO 2025-04-21 handle ICS file not being accessible

        with fn_cal.open(encoding="utf-8") as f:
            calendar_contents = f.read()
            ics_calendar = icalendar.Calendar.from_ical(calendar_contents)

        if str(ics_calendar["X-WR-CALNAME"]) != self.cal_name:
            return
        
        self.events_data = {}
        
        for event in ics_calendar.walk("VEVENT"):
            event_summary = str(event.get("SUMMARY"))
            print(f"{event_summary=}")

            new_ilsc_event = ILSCEvent(self)
            new_ilsc_event._ics_event = event.copy()
                
            #Only handle public events and those not conataining exclude tags
            if not new_ilsc_event.is_confidential and not new_ilsc_event.is_excluded and not new_ilsc_event.date_out_of_range:
                new_ilsc_event.populate_from_vcal_object()
                
                # determine limits of time range with timezone info
                today_in_the_morning_utc = dt.datetime.today().replace(hour=2, minute=0, second=0, microsecond=0, tzinfo=dt.UTC)
                limit_start_date = today_in_the_morning_utc + dt.timedelta(days=RANGE_MIN)
                limit_end_date = limit_start_date + dt.timedelta(days=RANGE_MAX)

                # handle different input types (dt.date or dt.datetime) with timezone info
                if isinstance(new_ilsc_event.dt_start, dt.datetime):
                    dt_start = new_ilsc_event.dt_start
                else:
                    dt_start = dt.datetime(year=new_ilsc_event.dt_start.year, month=new_ilsc_event.dt_start.month, day=new_ilsc_event.dt_start.day, tzinfo=TimeZone)

                if isinstance(new_ilsc_event.dt_end, dt.datetime):
                    dt_end = new_ilsc_event.dt_end
                else:
                    dt_end = dt.datetime(year=new_ilsc_event.dt_end.year, month=new_ilsc_event.dt_end.month, day=new_ilsc_event.dt_end.day, tzinfo=TimeZone)

                # check for limits
                if dt_start < limit_start_date:
                    print("event is in the past")
                    continue
                
                if dt_end > limit_end_date:
                    print("event is in the far future")
                    continue

                self.events_data[new_ilsc_event.key] = new_ilsc_event


    def read_from_cal_dav(self) -> None:
        '''read events from caldav calendar'''
        logger.debug(f'Connecting Calendar "{self.cal_name}"')

        start = time.time()
        try:
            self.client = caldav.DAVClient(self.cal_primary, username=self.cal_user,
                                      password=self.cal_passwd)
            self.principal = self.client.principal()
        except Exception as ex:
            logger.critical(f'Error on CALDav auth: {ex}')
            raise

        self.events_data = {}

        logger.debug('Time needed: {:.2f}s'.format(time.time() - start))
        start = time.time()

        logger.debug('Reading Events')
        for calendar in self.available_calendars():
            if calendar and calendar.name == self.cal_name:
                self.calendar = calendar
                #TODO: Check if timezone or utc converion is needed
                #had to add 2 hours else duplicates are created
                today_in_the_morning_utc = dt.datetime.today().replace(hour=2, minute=0, second=0, microsecond=0, tzinfo=dt.UTC)
                limit_start_date = today_in_the_morning_utc + dt.timedelta(days=RANGE_MIN)
                limit_end_date = limit_start_date + dt.timedelta(days=RANGE_MAX)
                
                logger.debug(f'Checking calendar "{self.cal_name}" for dates in range: {limit_start_date} to {limit_end_date}')
                
                try:
                    upcoming_events = calendar.date_search(
                        start=limit_start_date, end=limit_end_date, compfilter="VEVENT", expand=True)
                except:
                    #print("Your calendar server does apparently not support expanded search")
                    upcoming_events = calendar.date_search(
                        start=limit_start_date, end=limit_end_date, expand=False)
                #get all events
                #events = calendar.events()
                for event in upcoming_events:
                    if event.data:
                        try:
                            self.read_event(event)
                        except Exception as ex:
                            logger.error(f'Error reading event: {ex}')
        #uncomment as helper to check fetched events sorted by sektion and dates
        #dates = [value.key for (key, value) in sorted(self.events_data.items(), reverse=False)]
        logger.debug('Time needed: {:.2f}s'.format(time.time() - start))

    def available_calendars(self) -> list[caldav.Calendar]:
        cals = self.principal.calendars()
        logger.info(f'Fetching available calendars on: {self.cal_name}')
        logger.debug('Found:')
        for cal in cals:
            logger.debug(f'\t{cal.name}')
        return cals
    
    def read_event(self, calEvent: caldav.Event) -> None:
        '''read event data'''
        #TODO: Clean this mess. As there should only be one vevent component. at least if caldav filter is working
        cal = Calendar.from_ical(calEvent.data)
        components = cal.walk('vevent')
        #logger.debug(f'Nr of vevent components {len(components)}')
        for component in components:
            if component.name == "VEVENT":
                '''
                #only needed if parsing all events in calendar
                #TODO: check what this was for ^^
                edate = component.get('dtstart').dt
                if isinstance(edate, datetime):
                    edate = edate.date()
                #if edate >= date.start_date():
                '''
                ilsc_event = ILSCEvent(self)
                ilsc_event.calDAV = calEvent
                
                #Only handle public events and those not conataining exclude tags
                if not ilsc_event.is_confidential and not ilsc_event.is_excluded and not ilsc_event.date_out_of_range:
                    ilsc_event.populate_from_vcal_object()
                    self.events_data[ilsc_event.key] = ilsc_event
    
    def search_events_by_tags(self, tags:list) -> dict:
        '''search read events created by chronos with given tags
        #TODO: Check newer caldav version for direct search
        '''
        found = {}
        for key, event in self.events_data.items():
            if set(tags).issubset(event.categories) and event.is_chronos_origin:
                found[key] = event
        return found

    def search_events_by_calid(self, calid:str) -> dict[str, ILSCEvent]:
        '''search read events created by chronos with given calendar id'''
        found = {}
        for key, event in self.events_data.items():
            if calid == event.cal_id and event.is_chronos_origin:
                found[key] = event
        return found

class AppFactory:
    def __init__(self, config: appConfig):
        self.config = config
        self.scheduler = BackgroundScheduler({'apscheduler.timezone': self.config.get('app','timezone')})
        
        self.calendars: list[CalendarHandler] = []
        self.target = None
        
        self.active = False
    
    def create(self) -> None:
        
        _td, _cd, _icons = self.read_cal_config()
        
        self.set_calendars(_td, _cd, _icons)
        
        logger.debug('Base elements created')
    
    def read_cal_config(self) -> tuple[dict, dict, dict]:
        with open(self.config.get('calendars', 'file'), 'r', encoding='utf-8') as f:
            _data = json.load(f)
        return _data['target'], _data['calendars'], _data['icons']
        
    def set_calendars(self, target_data : list, calendars_data : dict, icons : dict) -> None:
        target_data['icons'] = icons
        self.target = CalendarHandler()
        self.target.config(target_data)
        
        for cal in calendars_data:
            cal['icons'] = icons
            _calendar = CalendarHandler()
            _calendar.config(cal)
            self.calendars.append(_calendar)
    
    def read_calendars(self) -> None:
        self.target.read()
        for c in self.calendars:
            c.read()
            
    def sanitize_events(self) -> None:
        for c in self.calendars:
            if c.sanitize_stati or c.sanitize_icons_src:
                for _, e in c.events_data.items():
                    if e.last_modified.astimezone(pytz.utc) > c.last_check.astimezone(pytz.utc):
                        save = False
                        if c.sanitize_stati:
                            save = bool(save + e.update_state_by_title())
                        if c.sanitize_icons_src: 
                            save = bool(save + e.set_title_icons())
                        if save:
                            e.save()
                            logger.debug(f"Updated source event: {e.date} | {e.safe_title}")
    
    def init_schedulers(self) -> None:
        #self.scheduler.add_job(lambda: self.start_data_collector(reset_count = True), 'cron', id=f"bigfish", hour=self.config.get('app', 'datacron'), minute=0)
        # self.scheduler.add_job(self.cron_app, 'cron', id="smallfish", hour=f'*/{self.config.get("app","appcron")}', minute=0)
        # self.scheduler.add_job(self.cron_app, 'cron', id="catfish", minute=f'{self.config.get("app","datacron")}')
        # self.scheduler.start()
        # TODO 2025-04-21 reenable schedulers. disabled for debugging.
        pass
    
    def run(self) -> None:
        self.active = True
        self.cron_app()
        while (self.active):
            time.sleep(60)
            #continue
    
    def stop(self) -> None:
        self.active = False
    
    def cron_app(self) -> None:
        try:
            self.read_calendars()
            logger.debug('Done parsing source calendars')
            self.sanitize_events()
            logger.debug('Cleaning up')
            self.sync_calendars()
            logger.debug('--== All done for this run ==--')
        except Exception as ex:
            logger.critical(f'Cron excecution failed. Reason {ex}')
    
    def sync_calendars(self) -> None:
        for c in self.calendars:
            changed, deleted, new = self.sync_calendar(c)
            c.last_check = TimeZone.localize(dt.datetime.now())
            logger.success(f'Done comparing with "{c.cal_name}". {len(changed)} entries updated. {len(new)} entries added. {len(deleted)} entries deleted.')
    
    def sync_calendar(self, calendar: CalendarHandler) -> tuple[dict, dict, dict]:
        #Update target calendar events from source calendar
        changed = self._update_target_events(calendar)
        #delete iCal event not in source calendar
        deleted = self._delete_target_events(calendar)
        #create iCal event only in source calendar
        new = self._create_target_events(calendar)
        return changed, deleted, new
    
    def _update_target_events(self, calendar: CalendarHandler) -> dict:
        '''Update target calendar events'''
        
        source_cal = calendar.events_data
        #target_cal = self.target.search_events_by_tags(calendar.tags)
        target_cal = self.target.search_events_by_calid(calendar.chronos_id)
        changeSet = set(target_cal).intersection(set(source_cal))
        changed = {}
        
        for eUID in changeSet:
            tgt = target_cal[eUID]
            src = source_cal[eUID]
            #TODO: (Re)Implement respect remote changes
            #if src.last_modified > tgt.last_modified and not tgt.remote_changed:
            if src.last_modified > tgt.last_modified:
                try:
                    changed[eUID] = tgt.update_calDaV_event(src)
                except Exception as ex:
                    logger.error(f'Could not update event: {ex}')
        return changed
    
    def _delete_target_events(self, calendar: CalendarHandler) -> dict:
        '''delete target iCal events not in source calendar'''
        source_cal = calendar.events_data
        #target_cal = self.target.search_events_by_tags(calendar.tags)
        target_cal = self.target.search_events_by_calid(calendar.chronos_id)
        deleteSet = set(target_cal).difference(set(source_cal))
        deleted = {}
        
        for eUID in deleteSet:
            try:
                if WIPE_ON_TARGET and target_cal[eUID].is_chronos_origin:
                    del_event = target_cal[eUID]
                    del_event.calDAV.delete()
                    logger.debug(f'Deleted: {del_event.date} | {del_event.safe_title}')
                    deleted[eUID] = del_event
            except Exception as ex:
                logger.error(f'Could not delete obsolete event: {ex}')
        return deleted
    
    def _create_target_events(self, calendar: CalendarHandler) -> dict:
        '''create iCal events only in source calendar'''
        source_cal = calendar.events_data
        #target_cal = self.target.search_events_by_tags(calendar.tags)
        target_cal = self.target.search_events_by_calid(calendar.chronos_id)
        newSet = set(source_cal).difference(set(target_cal))
        new_events: dict[vText, ILSCEvent] = {}

        for eUID in newSet:
            new_event = source_cal[eUID]
            if not(new_event.has_title):
                logger.debug(f'Ignoring event without title: {new_event.date}')
                continue
            if new_event.is_confidential:
                logger.debug(f'Ignoring confidential event: {new_event.date}')
                continue
            if new_event.is_excluded:
                logger.debug(f'Ignoring event excluded by tag: {new_event.date}')
                continue
            if ( calendar.ignore_planned and new_event.is_planned ) or new_event.is_canceled:
                logger.debug(f'Ignoring {new_event.status} event: {new_event.date} | {new_event.safe_title}')
                #skip planned events
                continue
            
            try: 
                _cal = Calendar()
                vevent = new_event.create_ical_event()
                
                _cal.add_component(vevent)
                _new = _cal.to_ical()
                self.target.calendar.add_event(_new, no_overwrite=True, no_create=False)
                logger.debug(f'Created: {new_event.date} | {new_event.safe_title}')
                new_events[eUID] = new_event
            except Exception as ex:
                logger.error(f'Could not create new event: {ex}')
                if new_event is not None and hasattr(new_event, 'title') and hasattr(new_event, 'date'):
                    logger.error(f'Affected event: {new_event.safe_title} {new_event.date}')
        return new_events