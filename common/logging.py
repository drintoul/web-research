import logging
import os
import sys
from pythonjsonlogger.json import JsonFormatter


def configure_logging(service: str) -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s %(service)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    logging.LoggerAdapter(logging.getLogger(service), {"service": service})
