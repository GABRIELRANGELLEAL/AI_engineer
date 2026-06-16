import logging
import json
from datetime import datetime
from config import LOG_LEVEL, LOG_FILE


class StructuredFormatter(logging.Formatter):
    """JSON structured logging formatter."""

    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if hasattr(record, "case_number"):
            log_data["case_number"] = record.case_number
        if hasattr(record, "filing_count"):
            log_data["filing_count"] = record.filing_count
        if hasattr(record, "exception") and record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "selector"):
            log_data["selector"] = record.selector
        if hasattr(record, "retry_attempt"):
            log_data["retry_attempt"] = record.retry_attempt

        return json.dumps(log_data)


def setup_logging():
    """Configure structured logging for the scraper."""
    logger = logging.getLogger("eproc_scraper")
    logger.setLevel(getattr(logging, LOG_LEVEL))

    # Remove existing handlers
    logger.handlers = []

    # File handler
    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(StructuredFormatter())
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    return logger


def get_logger():
    """Get the configured logger."""
    return logging.getLogger("eproc_scraper")


class LogContext:
    """Context manager for adding case_number to all logs in a block."""

    def __init__(self, case_number):
        self.case_number = case_number
        self.logger = get_logger()

    def __enter__(self):
        self.original_factory = logging.getLogRecordFactory()

        def factory(*args, **kwargs):
            record = self.original_factory(*args, **kwargs)
            record.case_number = self.case_number
            return record

        logging.setLogRecordFactory(factory)
        return self.logger

    def __exit__(self, *args):
        logging.setLogRecordFactory(self.original_factory)
