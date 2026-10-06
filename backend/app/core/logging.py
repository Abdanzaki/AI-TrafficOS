"""Structured logging configuration.

Configures application logging with a uvicorn-compatible formatter
including timestamp, level, and module information.
"""

import logging
import sys

LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s]: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root and application loggers with uvicorn-compatible formatting."""
    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    # Remove existing handlers to prevent duplicates if reconfigured
    root_logger.handlers = [handler]
    root_logger.setLevel(level)

    # Ensure app logger inherits this level and handler
    app_logger = logging.getLogger("app")
    app_logger.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Retrieve a configured logger instance."""
    return logging.getLogger(name)
