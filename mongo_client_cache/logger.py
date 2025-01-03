import functools
import logging

logger = logging.getLogger("mongo-client-cache")

# This logger is too noisy and it is disable by default.
_logger_debug = logging.getLogger("mongo-client-cache-debug")
_logger_debug.setLevel(logging.WARNING)
logger_debug = functools.partial(_logger_debug.debug)
