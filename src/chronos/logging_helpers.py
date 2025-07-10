from pathlib import Path
from typing import TYPE_CHECKING
import json
import logging
import logging.config

if TYPE_CHECKING:
    from chronos.config import Config


SUCCESS_LEVEL_NUM = 21


def _success_logging_function(
    self: logging.Logger,
    message: str,
    *args,
    **kws,
):
    if self.isEnabledFor(SUCCESS_LEVEL_NUM):
        # Yes, logger takes its '*args' as 'args'.
        self._log(
            SUCCESS_LEVEL_NUM,
            message,
            args,
            **kws,
        )


def init_logging(app_config: "Config") -> None:
    logging.addLevelName(
        SUCCESS_LEVEL_NUM,
        "SUCCESS",
    )
    LoggerClass = logging.getLoggerClass()
    setattr(LoggerClass, "success", _success_logging_function)

    # load preset for Pythons logging module
    fn_logging = Path(__file__).absolute().parent / "_logging_settings.json"
    if not fn_logging.exists():
        raise FileNotFoundError(fn_logging)

    with open(fn_logging, "r") as f:
        logging_settings = json.load(f)

    # resolve logging file paths and ensure parent directory existence
    filename_logging = Path(app_config.log["path"]) / app_config.log["filename"]
    if not filename_logging.parent.exists():
        filename_logging.parent.mkdir()

    # update logging handler with filename_logging
    handlers = logging_settings["handlers"]
    handlers["info_file_handler"]["filename"] = str(filename_logging)

    # hand in TimedRotatingFileHandler configuration
    handlers["info_file_handler"]["when"] = str(app_config.log["rotation"])
    handlers["info_file_handler"]["interval"] = int(app_config.log["interval"])
    handlers["info_file_handler"]["backupCount"] = int(app_config.log["backups"])

    logging.config.dictConfig(logging_settings)
