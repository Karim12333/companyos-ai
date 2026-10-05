import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

SENSITIVE_KEYS = ("password", "api_key", "apikey", "token", "secret", "authorization", "cookie", "credential")


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if _is_sensitive(key) else _redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _is_sensitive(key: Any) -> bool:
    return isinstance(key, str) and any(marker in key.lower() for marker in SENSITIVE_KEYS)


def redact_secrets(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    # Strip secret-looking keys from every log record
    return {
        key: ("[REDACTED]" if _is_sensitive(key) else _redact(value)) for key, value in event_dict.items()
    }


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    renderer: Any = structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_secrets,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )


def report_exception(error: BaseException, **context: Any) -> None:
    # Single hook point for an error tracker (e.g. Sentry) — logs structured for now
    structlog.get_logger("errors").error("exception", error=repr(error), **context, exc_info=error)


logger = structlog.get_logger("companyos")
