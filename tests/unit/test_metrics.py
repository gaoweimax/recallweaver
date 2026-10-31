"""Focused concurrency and sanitization tests for L6 observability."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
import sys

from recallweaver.observability.logging import JsonFormatter, _sanitize
from recallweaver.observability.metrics import MetricsCollector


def test_ten_threads_record_ten_thousand_recall_requests() -> None:
    """Ten concurrent callers produce the exact expected request count."""
    collector = MetricsCollector()

    def record_one_thousand() -> None:
        """Record 1,000 recall calls from a single worker thread."""
        for _ in range(1_000):
            collector.record_recall(0.25)

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(record_one_thousand)
            for _ in range(10)
        ]
        for future in futures:
            future.result()

    snapshot = collector.get_snapshot()
    assert snapshot["total_recall"] == 10_000
    assert snapshot["recall_latency_sum"] == 2_500.0
    assert snapshot["average_recall_latency"] == 0.25


def test_sanitize_redacts_api_key_and_bounds_long_text() -> None:
    """Sanitization hides key values and retains both ends of long text."""
    secret_text = "request api_key=super-secret-token rejected"
    sanitized_secret = _sanitize(secret_text)
    assert "super-secret-token" not in sanitized_secret
    assert "[REDACTED]" in sanitized_secret

    long_text = "A" * 60 + "PRIVATE-MIDDLE" + "Z" * 60
    sanitized_long_text = _sanitize(long_text)
    assert len(sanitized_long_text) == 43
    assert sanitized_long_text == "A" * 20 + "..." + "Z" * 20
    assert "PRIVATE-MIDDLE" not in sanitized_long_text


def test_json_formatter_includes_sanitized_exception_stack() -> None:
    """ERROR JSON includes a sanitized traceback excerpt in one log line."""
    try:
        raise RuntimeError("api_key=private-stack-secret")
    except RuntimeError:
        record = logging.LogRecord(
            name="recallweaver.api",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Request failed",
            args=(),
            exc_info=sys.exc_info(),
        )

    formatted = JsonFormatter().format(record)
    assert "\n" not in formatted
    assert '"level":"ERROR"' in formatted
    assert '"exception":' in formatted
    assert "private-stack-secret" not in formatted
