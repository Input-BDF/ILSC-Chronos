# -*- coding: utf-8 -*-
'''
Created on 25.02.2022

@author: input
'''
import caldav
import json
import pytz
import re
import time
import uuid

from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from hashlib import md5
from icalendar import Calendar, Event as icalEvent, vDDDTypes as icalDate, vText
from icalendar.prop import vCategory

from __main__ import appConfig

from core.log_factory import get_app_logger
import icalendar

logger = get_app_logger()

TimeZone = pytz.timezone(appConfig.get('app','timezone'))

APP_ID = appConfig.get('app', 'app_id')
RANGE_MIN = appConfig.get('calendars', 'range_min')
RANGE_MAX = appConfig.get('calendars', 'range_max')
WIPE_ON_TARGET = appConfig.get('calendars', 'delete_on_target')

class ILSCEvent(object):
    
    def __init__(self, source):
        self.source = source
        
        self.uid = uuid.uuid1()
        self.created = datetime.now()
        self.date = None
        self.description = None
        self.categories = []
        self.location = None
        
        self.calDAV = None
    
    def __repr__(self):
        return f"ILSCEvent - {self.date} | {self.title}"
    
    @property
    def title(self):
        return self._clear_title(self.ical.get('summary')) if self.ical else 'undefined'
    
    @property
    def safe_title(self):
        return re.sub(r'[^\x00-\x7F]+','', self.title)
    
    @property
    def ical(self) -> caldav.Event:
        return self.calDAV.icalendar_component if self.calDAV else None
    
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
    def last_modified(self) -> datetime:
        '''return last modification date. if event never was modified the creation date is provided'''
        _mod = self.ical.get('last-modified')
        return _mod.dt if _mod else self.ical.get('dtstamp').dt
    
    @property
    def origin(self) -> str:
        '''returns None if not set'''
        return self.ical.get('X-ILSC-ORIGIN')
    
    @property
    def source_uid(self) -> str:
        '''returns None if not set'''
        return self.ical.get('X-ILSC-UID')
    
    @property
    def prefixed_title(self) -> str:
        if self.source.title_prefix:
            return f"{self.source.title_prefix} | {self.title}"
        else:
            return self.title 
    
    @property
    def is_planned(self) -> bool:
        '''
        checks for ical status
            "TENTATIVE"           ;Indicates event is tentative.
            "CONFIRMED"           ;Indicates event is definite.
            "CANCELLED"           ;Indicates event is canceled
            returns True if satus is TENTATIVE
        '''
        return True if self.ical.get('status') == "TENTATIVE" else False
    
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
        confidential = False if ( not self.ical.get('class') ) or self.ical.get('class') == "PUBLIC" else True 
        return confidential
    
    @property
    def status(self):
        return self.ical.get('status')
    
    @property
    def date_start(self):
        #Allday:
        if self.source.all_day:
            return self.date
        #Timed:
        if self.source.force_time:
            try:
                _start_time = datetime.strptime(self.source.force_start, '%H:%M').time()
                return TimeZone.localize(datetime.combine(self.date, _start_time))
            except ValueError as ve:
                raise ValueError(f'Incompatible time format given. Check %H:%M - {ve}')
            except Exception as ex:
                logger.critical(f'Can not read calendars forced time configuration - {ex}')
                raise
        #Pass original date
        return self.ical.get('dtstart').dt
    
    @property
    def date_end(self):
        #Allday:
        if self.source.all_day:
            return self.date + timedelta(days=1)
        #Timed:
        if self.source.force_time:
            try:
                _end_time = datetime.strptime(self.source.force_end, '%H:%M').time()
                return TimeZone.localize(datetime.combine(self.date, _end_time))
            except ValueError as ve:
                raise ValueError(f'Incompatible time format given. Check %H:%M - {ve}')
            except Exception as ex:
                logger.critical(f'Can not read calendars forced time configuration - {ex}')
                raise
        #Pass original date
        return self.ical.get('dtend').dt

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

    def populate_from_vcal_object(self, event_object: caldav.Event):
        #TODO: enshure uid exists (at least it should )
        self.uid = str(event_object.get('uid'))
        self.created = event_object.get('dtstamp').dt
        self.date = event_object.get('dtstart').dt
        if isinstance(self.date, datetime):
            self.date = self.date.date()
        self.description = event_object.get('description')
        self.location = event_object.get('location')
        self.categories = self._parse_categories(event_object)
    
    def _clear_title(self, title: vText) -> str:
        '''
        Search for first occurance of any Prefix and replace
        Assumes that someone or thing added prefixes
        '''
        #TODO: collect all possible prefixes and match against them
        return re.sub(r"^([^\|]*\|)", "", title.to_ical().decode(), count=0, flags=0).strip()
    
    def _parse_categories(self, event: icalEvent) -> list:
        _cats = event.get('categories')
        if _cats:
            _cats = _cats.to_ical().decode().split(',')
            return _cats
        return []
    
    def combine_categories(self, first: list) -> list:
        return first.copy() + list(set(self.categories) - set(first))
    
    def sanitize_description(self) -> vText:
        try:
            _desc = self.description.to_ical().decode('utf-8')
        except:
            _desc = self.description.to_ical()
        #Remove multiline comments
        _reg_group = r"(###.*(?:###\\n|###))"
        _desc = re.sub(_reg_group,'', _desc)
        #Remove single line Comments
        _reg_line = r"#[^\\]*(?:\\[\s\S][^\\n]*)*\\n"
        _desc = re.sub(_reg_line,'', _desc)
        #Remove triple newlines
        _reg_double = r"(\\n\\n\\n)"
        _desc = re.sub(_reg_double,'', _desc)
        
        return icalendar.vText(_desc)
    
    def create_ical_event(self, iconize = False) -> icalEvent:
        new_event=icalEvent()
        _now = TimeZone.localize(datetime.now())

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
        self.calDAV.icalendar_component['last-modified'] = icalDate(datetime.now())
        
        self.calDAV.icalendar_component['status'] = src_event.status
        if ( src_event.source.ignore_planned and src_event.is_planned ) or src_event.is_confidential:
            #DELETE rather than save
            self.calDAV.delete()
            logger.success(f'Deleted {self.date} | {self.safe_title} out of the row in "{src_event.source.cal_name}".')
        else:
            self.calDAV.save()
        return self
    
    def set_title_icons(self, sep = ' | '):
        try:
            icons = set(self.categories).intersection(set(self.source.icons))
            
            if icons:
                icon_str = ""
                for i in icons:
                    icon_str += self.source.icons[i]
                _new_title = icalendar.vText(f"{icon_str}{sep}{self.title}")
                self.calDAV.icalendar_component['summary'] = _new_title
                logger.success(f"Event icons set for {self.date} | {self.safe_title}")
                return True
            #return False
        except Exception as ex:
            logger.error(f"Could not set event icons for {self.date} | {self.safe_title} - {ex}")
        
        return False
    
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

class CalendarHandler(object):
    
    def __init__(self):
        self.last_check = TimeZone.localize(datetime.now() + timedelta(days = -7))
        
        self.cal_primary = None
        self.cal_name = None
        self.cal_user = None
        self.cal_passwd = None
        
        self.all_day = True
        self.time_zone = "Europe/Berlin"
        self.force_time = False
        self.force_start = None
        self.force_end = None

        self.ignore_planned = False
        self.ignore_descriptions = False
        self.title_prefix = None
        self.tags = []
        self.color = None
        self.default_location = None
        
        self.sanitize_stati = False
        self.iconize = False
        
        self.events_data = {}
        
        self.client = None
        self.calendar = None
        self.principal = None
        self.icons = {}
        
    def config(self, conf_data):
        for key, val in conf_data.items():
            setattr(self, key, val) 
    
    def read(self):
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
                start_date = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days = RANGE_MIN)
                end_date = start_date + timedelta(days=RANGE_MAX)
                
                logger.debug(f'Checking calendar "{self.cal_name}" for dates in range: {start_date} to {end_date}')
                
                try:
                    upcoming_events = calendar.date_search(
                        start=start_date, end=end_date, compfilter="VEVENT", expand=True)
                except:
                    #print("Your calendar server does apparently not support expanded search")
                    upcoming_events = calendar.date_search(
                        start=start_date, end=end_date, expand=False)
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

    def available_calendars(self):
        cals = self.principal.calendars()
        logger.info(f'Available calendars on {self.cal_name}:')
        for cal in cals:
            logger.info(f'\t{cal.name}')
        return cals
    
    def read_event(self, calEvent: caldav.Event):
        '''read event data'''
        cal = Calendar.from_ical(calEvent.data)
        components = cal.walk('vevent')
        for component in components:
            if component.name == "VEVENT":
                edate = component.get('dtstart').dt
                if isinstance(edate, datetime):
                    edate = edate.date()
                #if edate >= date.start_date(): #only needed if parsing all events in calendar
                event = ILSCEvent(self)
                event.calDAV = calEvent
                event.populate_from_vcal_object(component)
                self.events_data[event.key] = event
    
    def search_events_by_tags(self, tags:list) -> dict:
        '''search read events created by chronos with given tags
        #TODO: Check newer caldav version for direct search
        '''
        found = {}
        for key, event in self.events_data.items():
            if set(tags).issubset(event.categories) and event.is_chronos_origin:
                found[key] = event
        return found

class AppFactory:
    def __init__(self, config: appConfig):
        self.config = config
        self.scheduler = BackgroundScheduler({'apscheduler.timezone': self.config.get('app','timezone')})
        
        self.calendars = []
        self.target = None
        
        self.active = False
    
    def create(self):
        
        _td, _cd, _icons = self.read_cal_config()
        
        self.set_calendars(_td, _cd, _icons)
        
        logger.debug('Base elements created')
    
    def read_cal_config(self):
        with open(self.config.get('calendars', 'file'), 'r', encoding='utf-8') as f:
            _data = json.load(f)
        return _data['target'], _data['calendars'], _data['icons']
        
    def set_calendars(self, target_data : list, calendars_data : dict, icons : dict):
        target_data['icons'] = icons
        self.target = CalendarHandler()
        self.target.config(target_data)
        
        for cal in calendars_data:
            cal['icons'] = icons
            _calendar = CalendarHandler()
            _calendar.config(cal)
            self.calendars.append(_calendar)
    
    def read_calendars(self):
        self.target.read()
        for c in self.calendars:
            c.read()
            
    def sanitize_events(self):
        for c in self.calendars:
            if c.sanitize_stati or c.iconize:
                for _, e in c.events_data.items():
                    if e.last_modified.astimezone(pytz.utc) > c.last_check.astimezone(pytz.utc):
                        save = False
                        if c.sanitize_stati:
                            save = bool(save + e.update_state_by_title())
                        if c.iconize: 
                            save = bool(save + e.set_title_icons())
                        if save:
                            e.save()
    
    def init_schedulers(self):
        #self.scheduler.add_job(lambda: self.start_data_collector(reset_count = True), 'cron', id=f"bigfish", hour=self.config.get('app', 'datacron'), minute=0)
        self.scheduler.add_job(self.cron_app, 'cron', id="smallfish", hour=f'*/{self.config.get("app","appcron")}', minute=0)
        self.scheduler.add_job(self.cron_app, 'cron', id="catfish", minute=f'{self.config.get("app","datacron")}')
        self.scheduler.start()
    
    def run(self):
        self.active = True
        self.cron_app()
        while (self.active):
            time.sleep(60)
            #continue
    
    def stop(self):
        self.active = False
    
    def cron_app(self):
        try:
            self.read_calendars()
            logger.debug('Done parsing source calendars')
            self.sanitize_events()
            logger.debug('Cleaning up')
            self.sync_calendars()
            logger.debug('--== All done for this run ==--')
        except Exception as ex:
            logger.critical(f'Cron excecution failed. Reason {ex}')
    
    def sync_calendars(self):
        for c in self.calendars:
            changed, deleted, new = self.sync_calendar(c)
            c.last_check = TimeZone.localize(datetime.now())
            logger.success(f'Done comparing with "{c.cal_name}". {len(changed)} entries updated. {len(new)} entries added. {len(deleted)} entries deleted.')
    
    def sync_calendar(self, calendar: CalendarHandler) -> (dict, dict, dict):
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
        target_cal = self.target.search_events_by_tags(calendar.tags)
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
        target_cal = self.target.search_events_by_tags(calendar.tags)
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
        target_cal = self.target.search_events_by_tags(calendar.tags)
        newSet = set(source_cal).difference(set(target_cal))
        new_events = {}

        for eUID in newSet:
            new_event = source_cal[eUID]
            if new_event.is_confidential:
                logger.debug(f'Ignoring confidential event: {new_event.date}')
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