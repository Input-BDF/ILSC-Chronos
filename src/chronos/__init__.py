from chronos import logging_helpers
from chronos.config import Config


app_config = Config()

logging_helpers.init_logging(app_config)
