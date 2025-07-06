from pathlib import Path
import json
import logging
import logging.config


SUCCESS_LEVELV_NUM = 21


def _success_logging_function(
    self: logging.Logger,
    message: str,
    *args,
    **kws,
):
    if self.isEnabledFor(SUCCESS_LEVELV_NUM):
        # Yes, logger takes its '*args' as 'args'.
        self._log(
            SUCCESS_LEVELV_NUM,
            message,
            args,
            **kws,
        )


def init_logging(chronos_config) -> None:
    logging.addLevelName(
        SUCCESS_LEVELV_NUM,
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
    filename_logging = Path(chronos_config.log["path"]) / chronos_config.log["filename"]
    if not filename_logging.parent.exists():
        filename_logging.parent.mkdir()

    # update logging handler with filename_logging
    handlers = logging_settings["handlers"]
    handlers["info_file_handler"]["filename"] = str(filename_logging)

    logging.config.dictConfig(logging_settings)

    # improve performance by disabling (currently unused) thread/process info in logs
    # logging.logThreads = False
    # logging.logProcesses = True
    # logging._srcfile = None
