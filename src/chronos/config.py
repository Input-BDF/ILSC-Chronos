"""
Created on 25.02.2022

@author: Input
"""

__all__ = ["CommandLine", "Config"]

import argparse
import configparser
import sys
import ast
import pathlib as pl
import logging

from collections import OrderedDict
from copy import deepcopy


logger = logging.getLogger(__name__)

CommandLine = argparse.ArgumentParser()
CommandLine.add_argument(
    "-c",
    "--config",
    type=str,
    action="store",
    help="Specify path to the configuration file",
    default="./config/app.cfg",
)
###Class definitions


class ConfigException(Exception):
    pass


class ConfigSection:
    def __init__(self, *params):
        self.params = OrderedDict()
        if params:
            for param in params:
                self.params[param.name] = param

    def __getitem__(self, key):
        if key not in self.params.keys():
            raise KeyError(f'ConfigSection has no key: "{key}"')
        return self.params[key].val

    def __setitem__(self, key, value):
        if isinstance(value, (ConfigValue, ConfigPath)):
            self.params[key] = value
        else:
            raise TypeError(f"Wrong type given to section. Allowed: [ConfigValue, ConfigPath] but delivered {type(value)}")

    def items(self):
        return [(k, v.val) for k, v in self.params.items()]

    def keys(self):
        return self.params.keys()

    def values(self):
        return self.params.values()

    def update(self, key, data):
        if key not in self.params.keys():
            raise ConfigException(f'ConfigSection has no key "{key}"')
        self.params[key].val = data

    def append(self, param):
        if param.name not in self.params.keys():
            self.params[param.name] = param
        else:
            raise KeyError('"{parameter.name}" already exists in this section.')

    def delete(self, key):
        del self.params[key]


class ConfigValue:
    """
    Unsupported/ Untested:
        Numeric Types:   range
        Binary Types:    bytearray, memoryview
        Set Types:       frozenset
    """

    def __init__(self, name, datatype=str, value=None, default=None):
        if datatype not in (
            str,
            int,
            float,
            complex,
            list,
            tuple,
            dict,
            bool,
            set,
            bytes,
        ):
            raise TypeError(f"Data type for {self.name} not supported for config file parsing: {datatype}")
        self._datatype = datatype
        self._value = None
        self._default = default

        self.name = name

        if value:
            self.val = value
        if default and not isinstance(default, datatype):
            raise TypeError(f"Default for {self.name} value has wrong type: {type(default)} Required: {datatype}")

    @property
    def default(self):
        return self._default

    @property
    def val(self):
        return self._value

    @val.setter
    def val(self, data):
        if isinstance(data, str) and data == "None":
            _val = None
        elif self._datatype is str and isinstance(data, str):
            _val = data
        elif isinstance(data, str):
            _val = self._eval_value(data)
        elif isinstance(data, self._datatype) or data is None:
            _val = data
        else:
            raise TypeError(f'Value for "{self.name}" has wrong type: {type(data)} Required: {self._datatype}')
        self._value = _val

    def apply_default(self):
        if self.val is None:
            self.val = deepcopy(self._default)

    def reset(self):
        self._value = deepcopy(self._default)

    def _eval_value(self, value):
        if self._datatype is bool:
            _true = (1, 1.0, True, "True", "true", "yes", "y")
            _false = (
                0,
                0.0,
                False,
                "False",
                "false",
                "no",
                "n",
            )
            if value in _true + _false:
                return True if value in (1, 1.0, True, "True", "true", "yes", "y") else False
                return bool(value)
            else:
                raise ValueError(f"Wrong value provided: {value} Allowed: [0, 0.0, False, false, no, n, 1, 1.0, True , true, yes, y]")
        try:
            _val = ast.literal_eval(value)
        except Exception:
            raise TypeError(f"Invalid raw value provided: {value}")
        if isinstance(_val, self._datatype):
            return _val
        else:
            raise TypeError(f"Value has wrong type: {type(_val)} Required: {self._datatype}")


class ConfigPath:
    def __init__(self, name, value=None, default=None, exists=False, create=False):
        self._path = None
        self._default = default
        self._exists = exists
        self._create = create

        self.name = name

        if value:
            self._convert_paths(value)

    def _convert_paths(self, path_str):
        if path_str is None:
            return
        p = pl.Path(self._check_posix_paths(path_str)).absolute()
        self._path = p
        if self._exists and not p.exists():
            if self._create:
                self._create_paths(p)
            else:
                logger.warning(f"Could not locate path at: {p}")

    def _check_posix_paths(self, path):
        try:
            if isinstance(path, str) and path.startswith("~"):
                p = pl.Path(path).expanduser()
                return p
            else:
                return path
        except NotImplementedError:
            raise Exception(f"Using this kind of path schema is not supported by your OS: {path}")
        except Exception as ex:
            raise Exception(f"Critical: {ex}")

    def _create_paths(self, path):
        try:
            path.mkdir(0o644, parents=True, exist_ok=True)
            logger.info(f"Creating path: {path}")
        except Exception as ex:
            logger.critical(f"Could not crate {path}: {ex}")
            raise

    @property
    def default(self):
        return self._default

    @property
    def val(self):
        return self._path

    @val.setter
    def val(self, data):
        self._convert_paths(data)

    def apply_default(self):
        if self.val is None:
            self.val = deepcopy(self._default)


class Config:
    """
    app configuration class
    """

    ###Globals and Default values
    # Private attributes
    MULTIPLE_VALUE_DELIMITER = ","

    # Public methods
    def __init__(self):
        # All sections
        logger.info("Init Configuration...")

        self.sections = [
            "app",
            "calendars",
            "log",
            "debug",
        ]
        # Parsed files
        self.files = []

        # Section [app]
        self.app = ConfigSection(
            ConfigValue("timezone", value=None, default="Europe/Berlin"),
            # run gspread and caldav on n-th hour of day
            ConfigValue("datacron", default="10"),
            # run gspread and caldav parser every n-th hour of day
            ConfigValue("appcron", int, value=None, default=4),
            ConfigValue("app_id", default="Chronos"),
        )

        # Section [calendars]
        self.calendars = ConfigSection(
            ConfigPath("path", default="./config", exists=True, create=False),
            ConfigValue("filename", default="calendars.json"),
            ConfigPath("file"),
            ConfigValue("range_min", int, default=0),
            ConfigValue("range_max", int, default=365),
            ConfigValue("delete_on_target", bool, default=True),
            ConfigValue("prefix_format", default="$icons $prefix"),
        )

        # Section [log]
        self.log = ConfigSection(
            ConfigPath("path", default="./logs/", exists=True, create=False),
            ConfigValue("filename", default="application.log"),
            ConfigPath("file"),
            ConfigValue("level", default="INFO"),
            ConfigValue("rotation", default="d"),
            ConfigValue("interval", int, default=1),
            ConfigValue("backups", int, default=7),
        )
        # Section [debug]
        self.debug = ConfigSection(
            ConfigValue("remote", bool, default=False),
            ConfigValue("remote_server", default="127.0.0.1"),
            ConfigPath(
                "remote_workdir",
                default="./RemoteSystemsTempFiles",
                exists=False,
                create=False,
            ),
            ConfigValue("remote_iface_nr", int, default=0),
            ConfigValue("remote_interface", default="eth0"),
        )
        self.appCL = CommandLine.parse_args()
        self._read_commandline_config()
        self._configure_file_paths()

        logger.info("Configuration successful")

    def get(self, section, param):
        return getattr(self, section)[param]

    def read(self, filename: pl.Path):
        """
        Reads configuration file
        """

        if not filename.exists():
            raise FileNotFoundError(f"file not found: {filename}")

        try:
            self.parser = configparser.ConfigParser(allow_no_value=False)
            # self.files = self.parser.read(filename, encoding='utf-8')
            self.files = self.parser.read(filename)
            if not self.files:
                raise IOError("failed to read a configuration file")
            for section in self.parser.sections():
                try:
                    for key, value in self.parser.items(section):
                        try:
                            getattr(self, section).update(key, value)
                        except Exception as ex:
                            print(f'Ivalid parameter "{key}" in "[{section}]": {ex}')
                            pass
                except configparser.NoSectionError as NSE:
                    print(f"Section not found in config: {NSE}")
            self.apply_defaults()
        except (
            configparser.ParsingError,
            configparser.MissingSectionHeaderError,
        ) as ex:
            print(ex)
            raise IOError("failed to parse a configuration file")

    def apply_defaults(self):
        for section in self.sections:
            for value in getattr(self, section).values():
                value.apply_default()

    def write_file(self):
        for section in self.sections:
            self._write(section, getattr(self, section))
            for value in getattr(self, section).values():
                value.apply_default()

    def _configure_file_paths(self):
        calendar_filename = self.get("calendars", "path").joinpath(self.get("calendars", "filename"))
        self.calendars.update("file", calendar_filename)

        log_filename = self.get("log", "path").joinpath(self.get("log", "filename"))
        self.log.update("file", log_filename)

    def _read_commandline_config(self):
        if self.appCL.config:
            self.appCL.config = pl.Path(self.appCL.config).resolve()
            try:
                self.read(self.appCL.config)
            except Exception as ex:
                logger.critical(f"{sys.argv[0]} : {ex}")
                sys.exit(1)

    def _write(self, section, data):
        """
        writes configuration file
        """
        # TODO: check if really needed and if everything works
        if not self.files:
            raise IOError("failed to read a configuration file")
        if not self.parser:
            raise IOError("config parser not present")
        try:
            for key, value in data.items():
                self.parser.set(section, key, str(value))
            # Writing our configuration file to 'filename'
            with open(self.files[0], "w") as configfile:
                self.parser.write(configfile)
            return True
        except Exception as ex:
            raise IOError(f"Failed writing config section {section}: {ex}")

    def __repr__(self):
        """
        Returns a string representation of a Config object
        """
        s = f"from <{('; '.join(self.files))}>\n"
        for section in self.sections:
            s += f"[{section}]\n"
            try:
                for key, value in getattr(self, section).items():
                    s += f"\t{key} = {value}\n"
            except AttributeError as a:
                print(a)
                pass
        return s

    def dict(self):
        """
        return configuration as dictionary
        """
        d = {}
        for section in self.sections:
            d[section] = {}
            try:
                for key, value in getattr(self, section).items():
                    d[section][key] = value
            except AttributeError as a:
                print(a)
                pass
        return d
