"""Structured JSON logging with basic secret redaction and message limits."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import re
from typing import Final


_SECRET_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"""(?ix)
    (?P<prefix>["']?(?:api[_-]?key|password)["']?\s*
    (?:[:=]|\bis\b)\s*)
    (?P<secret>"[^"]*"|'[^']*'|[^\s,;}]+)
    """
)
_MAX_MESSAGE_LENGTH: Final[int] = 100
_LOGGER_HANDLER_MARKER: Final[str] = "_recallweaver_json_handler"


def _sanitize(text: str) -> str:
    """Redact credentials and bound arbitrary text before it reaches a log.

    Args:
        text: Log message, exception text, or other potentially sensitive text.

    Returns:
        Sanitized, single-line text no longer than 100 characters.
    """
    sanitized = _SECRET_PATTERN.sub(
        lambda match: f"{match.group('prefix')}[REDACTED]",
        text,
    )
    sanitized = sanitized.replace("\r", "\\r").replace("\n", "\\n")
    if len(sanitized) > _MAX_MESSAGE_LENGTH:
        prefix = sanitized[:20]
        redaction_marker = "[REDACTED]"
        marker_position = sanitized.find(redaction_marker)
        if 0 <= marker_position < 40:
            marker_end = marker_position + len(redaction_marker)
            if marker_end > len(prefix):
                prefix = sanitized[:marker_end]
        sanitized = prefix + "..." + sanitized[-20:]
    return sanitized


class JsonFormatter(logging.Formatter):
    """Serialize each logging record as one sanitized JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        """Format timestamp, severity, module, and a safe message as JSON.

        Args:
            record: Logging event produced by the standard library.

        Returns:
            One compact JSON object on a single line.
        """
        timestamp = datetime.fromtimestamp(
            record.created,
            timezone.utc,
        ).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        payload = {
            "time": timestamp,
            "timestamp": timestamp,
            "level": record.levelname,
            "module": record.name,
            "message": _sanitize(record.getMessage()),
        }
        if record.exc_info:
            payload["exception"] = _sanitize(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def get_logger(name: str) -> logging.Logger:
    """Get a standard logger configured with the safe JSON formatter.

    The logger is configured only once, so repeated API construction does not
    add duplicate stream handlers.

    Args:
        name: Logger/module name included in each structured event.

    Returns:
        A standard-library logger that emits one JSON line per event.

    Raises:
        TypeError: If ``name`` is not a string.
        ValueError: If ``name`` is empty or contains only whitespace.
    """
    if not isinstance(name, str):
        raise TypeError("logger name 必须是字符串")
    if not name.strip():
        raise ValueError("logger name 不能为空")

    logger = logging.getLogger(name)
    if not any(
        getattr(handler, _LOGGER_HANDLER_MARKER, False)
        for handler in logger.handlers
    ):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        setattr(handler, _LOGGER_HANDLER_MARKER, True)
        logger.addHandler(handler)
    if logger.level == logging.NOTSET:
        logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
