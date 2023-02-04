# -*- coding: utf-8 -*-
'''
Created on 29.01.2022

@author: input
'''

import os

import logging
from logging.handlers import TimedRotatingFileHandler

from colorama import init,Fore, Back, Style

###
# Formats
LogInfo = '[%(levelname)s] %(asctime)s: %(message)s'
LogFormatExt = '[%(levelname)s] %(asctime)s - %(message)s -- %(module)s:%(funcName)s @ %(filename)s (Line %(lineno)s)'

###
# Levels
SUCCESS_LEVELV_NUM = 21

def success(self, message, *args, **kws):
    if self.isEnabledFor(SUCCESS_LEVELV_NUM):
        # Yes, logger takes its '*args' as 'args'.
        self._log(SUCCESS_LEVELV_NUM, message, args, **kws) 

class CustomLogFormatter(logging.Formatter):
    '''
    see and more: https://stackoverflow.com/a/56944256
    '''

    FORMATS = {
        SUCCESS_LEVELV_NUM: f'{Fore.GREEN}{LogInfo}{Style.RESET_ALL}',
        logging.DEBUG: f'{Fore.LIGHTBLACK_EX}{LogInfo}{Style.RESET_ALL}',
        logging.INFO: f'{Fore.WHITE}{LogInfo}{Style.RESET_ALL}',
        logging.WARNING: f'{Fore.RED}{LogFormatExt}{Style.RESET_ALL}',
        logging.ERROR: f'{Back.RED}{LogFormatExt}{Style.RESET_ALL}',
        logging.CRITICAL: f'{Back.RED}{Style.BRIGHT}{LogFormatExt}{Style.RESET_ALL}',
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


def create():
    #use convert only only when developing on windoof directly
    _conv = True if os.name == 'nt' else False
    init(autoreset=True, convert=True, strip=False) #Init Colorama
    
    logging.addLevelName(SUCCESS_LEVELV_NUM, "SUCCESS")
    logging.Logger.success = success
    
    logger = get_app_logger()
    
    logger.setLevel(logging.getLevelName('DEBUG'))
    # create console handler with a higher log level
    consolelog = logging.StreamHandler()
    consolelog.setLevel(logging.DEBUG)
    consolelog.setFormatter(CustomLogFormatter())
    logger.addHandler(consolelog)
    return logger

def init_config(log_config):
    logFile=log_config['file']
    logLevel = log_config['level']
    
    logger = get_app_logger()
    
    if logLevel == 'DEBUG':
        #create logFile in debug mode to get everything from every module supporting logging
        logging.basicConfig(format=LogFormatExt,
                            filename=f'{logFile}_debug',
                            level=logging.getLevelName(logLevel))
    
    loghandler = TimedRotatingFileHandler(logFile,
                                          when=log_config['rotation'],
                                          interval=int(log_config['interval']),
                                          backupCount=int(log_config['backups']))
    
    loghandler.setFormatter(logging.Formatter(LogInfo))
    
    logger.addHandler(loghandler)
    logger.setLevel(logging.getLevelName(logLevel))


def get_app_logger():
    logger = logging.getLogger('app_chronicles')
    return logger