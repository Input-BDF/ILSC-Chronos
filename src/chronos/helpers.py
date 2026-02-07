import datetime as dt
import zoneinfo
from html.parser import HTMLParser
from logging import Logger

from bs4 import BeautifulSoup

from chronos.config import Config


def convert_to_date_or_timezone_datetime(date_or_datetime: dt.date | dt.datetime, time_zone: zoneinfo.ZoneInfo) -> dt.date | dt.datetime:
    """convert to given timezone if the type is `datetime` else leave it as date."""

    if type(date_or_datetime) is dt.datetime:
        result = date_or_datetime.astimezone(time_zone)
    elif type(date_or_datetime) is dt.date:
        result = date_or_datetime
    else:
        raise ValueError(f"argument type ({type(date_or_datetime)}) not supported")
    return result


def convert_to_date_or_utc_datetime(
    date_or_datetime: dt.date | dt.datetime,
) -> dt.date | dt.datetime:
    """convert to UTC timezone if the type is `datetime` else leave it as date."""

    if type(date_or_datetime) is dt.datetime:
        result = date_or_datetime.astimezone(zoneinfo.ZoneInfo("UTC"))
    elif type(date_or_datetime) is dt.date:
        result = date_or_datetime
    else:
        raise ValueError(f"argument type ({type(date_or_datetime)}) not supported")
    return result


def enable_remote_debug(app_config: Config, logger: Logger):
    try:
        from os import path as ospath

        import netifaces as ni

        logger.debug("RemoteDebug: Initializing")
        _remote_ip = app_config.get("debug", "remote_server")
        _remote_wd = app_config.get("debug", "remote_workdir")
        _int_part = app_config.get("debug", "remote_iface_nr")
        # In some cases interface has two adresses.
        # refer https://pypi.org/project/netifaces/
        _ifaces = ni.ifaddresses(app_config.get("debug", "remote_interface"))
        _local_ip = _ifaces[ni.AF_INET][int(_int_part)]["addr"]
        logger.debug(f"RemoteDebug: Running on {_local_ip}")
        _path = ospath.dirname(ospath.abspath(__file__)).replace("/", "\\")
    except Exception as ex:
        logger.debug(f"RemoteDebug: Init failed: {ex}")
        logger.debug(f"RemoteDebug: Available ifaces: {_ifaces}")
        return
    try:
        import pydevd
        from pydevd_file_utils import setup_client_server_paths

        MY_PATHS_FROM_ECLIPSE_TO_PYTHON = [
            (rf"{_remote_wd}\{_local_ip}{_path}", rf"{_path}"),
            (rf"{_remote_wd}\{_local_ip}\usr\local\bin", r"/usr/local/bin"),
        ]
        setup_client_server_paths(MY_PATHS_FROM_ECLIPSE_TO_PYTHON)
        pydevd.settrace(_remote_ip, stdoutToServer=True, stderrToServer=True)

    except ImportError:
        logger.debug("RemoteDebug: Could not import pydevd")
    except Exception as ex:
        logger.debug(f"RemoteDebug: General Exception {ex}")


class HTMLFilter(HTMLParser):
    """
    small helper class to eliminate HTML tags from a text.
    thanks, https://stackoverflow.com/a/55825140
    """

    def __init__(self):
        super().__init__()
        self.text = ""

    def handle_data(self, data):
        self.text += data


def sanitize_link_with_line_breaks(text_input: str) -> str:
    # handle links with BeautifulSoup
    soup = BeautifulSoup(text_input, "html.parser")

    for data in soup(["a"]):
        brs = data.find_all("br")
        if len(brs) > 0:
            pass

        anchor_url = data.get("href")
        if anchor_url is None:
            continue

        anchor_text = data.string
        if anchor_text is None:
            continue

        replacement_text = anchor_url
        amount_line_breaks = anchor_text.count("\\n")
        sanitized_anchor_text = anchor_text.replace("\\n", "")
        if anchor_url != sanitized_anchor_text:
            replacement_text = f"{sanitized_anchor_text} ({anchor_url})"

        replacement_text += " " + "\\n" * amount_line_breaks
        print(replacement_text)

        data.string = str(replacement_text)

    text_without_links = "".join(soup.stripped_strings)
    return text_without_links
