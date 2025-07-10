"""
Created on 24.02.2022

@author: input
"""

import logging

from chronos import helpers
from chronos.config import Config
from chronos.app_factory import AppFactory
from chronos import logging_helpers


def main():
    # initialize all stuff
    logger = logging.getLogger("chronos")

    app_config = Config()
    logging_helpers.init_logging(app_config)
    if app_config.get("debug", "remote"):
        helpers.enable_remote_debug(app_config, logger)

    logger.info("---- Initialized - going up ----")

    try:
        factory = AppFactory(app_config)
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
