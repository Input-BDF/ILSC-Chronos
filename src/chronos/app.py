"""
Created on 24.02.2022

@author: input
"""

import logging

from chronos import helpers
from chronos.config import Config
from chronos.app_factory import AppFactory


def main():
    # initialize all stuff
    logger = logging.getLogger("chronos")

    appConfig = Config()
    if appConfig.get("debug", "remote"):
        helpers.enable_remote_debug(appConfig, logger)

    logger.info("---- Initialized - going up ----")

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
