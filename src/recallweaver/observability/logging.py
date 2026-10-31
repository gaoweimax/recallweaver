"""Structured JSON logging with basic secret redaction and message limits."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
import json
import logging
import os
import re
from pathlib import Path
from collections.abc import Iterator
from typing import Any, Final
from uuid import uuid4

from rich.console import Console
from rich.logging import RichHandler


_SECRET_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"""(?ix)
    (?P<prefix>["']?(?:api[_-]?key|password)["']?\s*
    (?:[:=]|\bis\b)\s*)
    (?P<secret>"[^"]*"|'[^']*'|[^\s,;}]+)
    """
)
_MAX_MESSAGE_LENGTH: Final[int] = 100
_RICH_HANDLER_MARKER: Final[str] = "_recallweaver_rich_handler"
_FILE_HANDLER_MARKER: Final[str] = "_recallweaver_json_file_handler"
_TRACE_ID: ContextVar[str] = ContextVar("recallweaver_trace_id", default="-")


class HumanFormatter(logging.Formatter):
    """Render concise colored-terminal messages with the active trace ID."""

    def format(self, record: logging.LogRecord) -> str:
        """Format one terminal line with timestamp, severity, trace, and module.

        Args:
            record: Logging event produced by the standard library.

        Returns:
            A sanitized human-readable line for RichHandler.
        """
        timestamp = datetime.fromtimestamp(record.created).strftime(
            "%Y-%m-%d %H:%M:%S."
        ) + f"{int(record.msecs):03d}"
        trace_id = _sanitize(_TRACE_ID.get())
        module = _sanitize(record.name)
        message = _sanitize(record.getMessage())
        return (
            f"[{timestamp}] [{record.levelname}] [Trace:{trace_id}] "
            f"[{module}] {message}"
        )


@contextmanager
def trace_context(trace_id: str | None = None) -> Iterator[str]:
    """Bind a unique trace ID to the current execution context.

    Context variables naturally propagate through asyncio task contexts and
    isolate concurrent requests from one another.

    Args:
        trace_id: Optional externally supplied trace ID. A UUID is generated
            when omitted.

    Yields:
        The bound trace ID for the lifetime of the context manager.
    """
    selected_trace_id = trace_id or uuid4().hex
    token = _TRACE_ID.set(selected_trace_id)
    try:
        yield selected_trace_id
    finally:
        _TRACE_ID.reset(token)


def get_trace_id() -> str:
    """Return the trace ID currently bound to this execution context."""
    return _TRACE_ID.get()


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


def _sanitize_value(value: Any) -> Any:
    """Sanitize nested values before serializing them into structured logs.

    Args:
        value: Any JSON-like value supplied as log details.

    Returns:
        A JSON-compatible value with all text sanitized.
    """
    if isinstance(value, str):
        return _sanitize(value)
    if isinstance(value, dict):
        return {
            _sanitize(str(key)): (
                "[REDACTED]"
                if re.fullmatch(
                    r"(?i)(?:api[_-]?key|password)",
                    str(key),
                )
                else _sanitize_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _sanitize(str(value))


class JsonFormatter(logging.Formatter):
    """Serialize each logging record as one sanitized JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        """Format timestamp, severity, module, and a safe message as JSON.

        Args:
            record: Logging event produced by the standard library.

        Returns:
            One compact JSON object on a single line.
        """
        timestamp = datetime.fromtimestamp(record.created).strftime(
            "%Y-%m-%d %H:%M:%S."
        ) + f"{int(record.msecs):03d}"
        message = _sanitize(record.getMessage())
        action = _sanitize(
            str(getattr(record, "action", record.funcName or "log"))
        )
        details = _sanitize_value(
            getattr(record, "details", message)
        )
        payload = {
            "timestamp": timestamp,
            "level": record.levelname,
            "trace_id": _sanitize(_TRACE_ID.get()),
            "module": record.name,
            "action": action,
            "details": details,
            "time": timestamp,
            "message": message,
        }
        if record.exc_info:
            payload["exception"] = _sanitize(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def get_logger(name: str) -> logging.Logger:
    """Get a logger configured for Rich console and JSON file output.

    The logger is configured only once, so repeated API construction does not
    add duplicate handlers. The file path can be customized with
    ``RECALLWEAVER_LOG_FILE``; otherwise logs are stored under the user's
    ``.recallweaver`` directory.

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
        getattr(handler, _RICH_HANDLER_MARKER, False)
        for handler in logger.handlers
    ):
        rich_handler = RichHandler(
            console=Console(stderr=True),
            show_time=False,
            show_level=False,
            show_path=False,
            markup=False,
        )
        rich_handler.setFormatter(HumanFormatter())
        setattr(rich_handler, _RICH_HANDLER_MARKER, True)
        logger.addHandler(rich_handler)

    if not any(
        getattr(handler, _FILE_HANDLER_MARKER, False)
        for handler in logger.handlers
    ):
        log_path = Path(
            os.environ.get(
                "RECALLWEAVER_LOG_FILE",
                str(Path.home() / ".recallweaver" / "recallweaver.jsonl"),
            )
        ).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(JsonFormatter())
        setattr(file_handler, _FILE_HANDLER_MARKER, True)
        logger.addHandler(file_handler)
    if logger.level == logging.NOTSET:
        logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
