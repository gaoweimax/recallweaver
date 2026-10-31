"""Tests for timestamped, privacy-safe JSON logging."""

from __future__ import annotations

from datetime import datetime
import json
import logging
import re
from logging import FileHandler

from rich.logging import RichHandler
from recallweaver.observability.logging import (
    JsonFormatter,
    _sanitize,
    get_logger,
    trace_context,
)


def test_json_log_timestamp_uses_millisecond_format() -> None:
    """Every formatted record carries a parseable millisecond timestamp."""
    record = logging.LogRecord(
        name="recallweaver.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="operation complete",
        args=(),
        exc_info=None,
    )

    payload = json.loads(JsonFormatter().format(record))
    timestamp = payload["timestamp"]

    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}",
        timestamp,
    )
    assert datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S.%f")
    assert {
        "timestamp",
        "level",
        "module",
        "action",
        "details",
    }.issubset(payload)


def test_json_log_sanitizes_credentials_and_long_text() -> None:
    """Structured details redact API keys and limit oversized strings."""
    record = logging.LogRecord(
        name="recallweaver.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="request rejected",
        args=(),
        exc_info=None,
    )
    record.action = "request"
    record.details = {
        "api_key": "do-not-log-this",
        "message": "sensitive " * 20,
    }

    payload = json.loads(JsonFormatter().format(record))

    assert payload["details"]["api_key"] == "[REDACTED]"
    assert "do-not-log-this" not in json.dumps(payload)
    assert len(payload["details"]["message"]) <= 100
    assert "..." in payload["details"]["message"]
    assert "[REDACTED]" in _sanitize("api_key=private-token")
    assert "private-token" not in _sanitize("api_key=private-token")


def test_json_log_carries_bound_trace_id() -> None:
    """A context-bound trace ID is attached to JSON records in that request."""
    record = logging.LogRecord(
        name="recallweaver.api",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request started",
        args=(),
        exc_info=None,
    )
    record.action = "recall_start"
    record.details = {"query": "张三"}

    with trace_context("trace-test-123"):
        payload = json.loads(JsonFormatter().format(record))

    assert payload["trace_id"] == "trace-test-123"
    assert payload["module"] == "recallweaver.api"
    assert payload["action"] == "recall_start"
    assert payload["details"] == {"query": "张三"}


def test_api_recall_returns_trace_id_for_cli_correlation(tmp_path) -> None:
    """Every result from one recall shares the request's generated trace ID."""
    from recallweaver.api import RecallWeaverAPI

    api = RecallWeaverAPI(str(tmp_path / "trace.db"))
    api.remember_triple("张三", "居住于", "杭州")

    results = api.recall("张三")

    assert results
    trace_ids = {result.trace_id for result in results}
    assert len(trace_ids) == 1
    assert None not in trace_ids


def test_logger_uses_rich_console_and_json_file_handlers(
    tmp_path,
    monkeypatch,
) -> None:
    """Logger output is colorful in terminal and structured in its JSON file."""
    log_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("RECALLWEAVER_LOG_FILE", str(log_path))
    logger = get_logger(f"recallweaver.test.handlers.{tmp_path.name}")

    rich_handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, RichHandler)
    ]
    file_handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, FileHandler)
    ]

    assert len(rich_handlers) == 1
    assert len(file_handlers) == 1
    rich_handlers[0].setLevel(logging.CRITICAL)
    with trace_context("file-trace"):
        logger.info(
            "operation",
            extra={"action": "test", "details": {"status": "ok"}},
        )

    payload = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert payload["trace_id"] == "file-trace"
    assert payload["action"] == "test"
    assert payload["details"] == {"status": "ok"}
