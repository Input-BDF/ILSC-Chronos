from core import logging_helpers
from core.config import Config


app_config = Config()

logging_helpers.init_logging(app_config)
