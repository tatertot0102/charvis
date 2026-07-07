"""Structured logging (structlog) — JSON logs with timestamps and levels."""
import logging

import structlog


def configure_logging(level: int = logging.INFO) -> None:
    """Configure structlog to emit JSON. Call once at startup."""
    logging.basicConfig(format="%(message)s", level=level)

    # Silence noisy third-party request logs. Critically, python-telegram-bot's httpx client
    # logs full request URLs at INFO — which include the bot token. Keep those at WARNING so
    # the token never lands in logs (see security rules: redact credentials from logs).
    for noisy in ("httpx", "httpcore", "telegram", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
