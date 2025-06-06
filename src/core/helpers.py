from logging import Logger
from core.config import Config


def enable_remote_debug(app_config: Config, logger: Logger):
    try:
        import netifaces as ni
        from os import path as ospath
        logger.debug('RemoteDebug: Initializing')
        _remote_ip = app_config.get('debug', 'remote_server')
        _remote_wd = app_config.get('debug', 'remote_workdir')
        _int_part = app_config.get('debug', 'remote_iface_nr')
        #In some cases interface has two adresses. 
        #refer https://pypi.org/project/netifaces/
        _ifaces = ni.ifaddresses(app_config.get('debug', 'remote_interface'))
        _local_ip = _ifaces[ni.AF_INET][int(_int_part)]['addr']
        logger.debug(f'RemoteDebug: Running on {_local_ip}')
        _path = ospath.dirname(ospath.abspath(__file__)).replace('/','\\')
    except Exception as ex:
        logger.debug(f'RemoteDebug: Init failed: {ex}')
        logger.debug(f'RemoteDebug: Available ifaces: {_ifaces}')
        return
    try: 
        import pydevd
        from pydevd_file_utils import setup_client_server_paths
        MY_PATHS_FROM_ECLIPSE_TO_PYTHON = [
            (fr'{_remote_wd}\{_local_ip}{_path}', fr'{_path}'),
            (fr'{_remote_wd}\{_local_ip}\usr\local\bin', r'/usr/local/bin'),
        ]
        setup_client_server_paths(MY_PATHS_FROM_ECLIPSE_TO_PYTHON)
        pydevd.settrace(_remote_ip ,stdoutToServer=True, stderrToServer=True)
        
    except ImportError:
        logger.debug('RemoteDebug: Could not import pydevd')
    except Exception as ex:
        logger.debug(f'RemoteDebug: General Exception {ex}')