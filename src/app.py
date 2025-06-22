"""
Created on 24.02.2022

@author: input
"""

import logging

from core import helpers
from core.config import Config
from core.app_factory import AppFactory

###
# Init all stuff
try:
    appConfig = Config()
    logger = logging.getLogger("chronos")
except Exception as ex:
    print(ex)

if appConfig.get("debug", "remote"):
    helpers.enable_remote_debug(appConfig, logger)


logger.info("---- Initialized - going up ----")


def main():
    try:
        factory = AppFactory(appConfig)
        factory.create()
        factory.init_schedulers()
        factory.run()
    except Exception as ex:
        logger.critical(f"Error on main thread: {ex}", exc_info=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        print(ex)
