"""Unit tests for structured logging and concurrent in-memory metrics."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import logging

from recallweaver.api import RecallWeaverAPI
from recallweaver.observability.logging import JsonFormatter
from recallweaver.observability.metrics import MetricsCollector


def test_json_formatter_redacts_secrets_and_truncates_long_messages() -> None:
    """Credentials are redacted and long log payloads are bounded."""
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="recallweaver.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg='{"api_key": "secret-token", "password": "do-not-log"} '
        + ("private text " * 20),
        args=(),
        exc_info=None,
    )

    formatted = formatter.format(record)
    payload = json.loads(formatted)

    assert "\n" not in formatted
    assert payload["level"] == "ERROR"
    assert payload["module"] == "recallweaver.test"
    assert payload["timestamp"].endswith("Z")
    assert "secret-token" not in formatted
    assert "do-not-log" not in formatted
    assert "[REDACTED]" in payload["message"]
    assert len(payload["message"]) <= 100
    assert payload["message"].endswith("...")


def test_metrics_collector_is_thread_safe_for_recall_updates() -> None:
    """Concurrent updates preserve exact counters and latency sum."""
    collector = MetricsCollector()
    calls_per_worker = 500
    worker_count = 16

    def record_worker(worker_number: int) -> None:
        """Record distinct deterministic durations from one worker."""
        for call_number in range(calls_per_worker):
            collector.record_recall(float(worker_number + call_number))

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        list(executor.map(record_worker, range(worker_count)))

    expected_count = worker_count * calls_per_worker
    expected_latency_sum = sum(
        worker_number + call_number
        for worker_number in range(worker_count)
        for call_number in range(calls_per_worker)
    )
    snapshot = collector.get_snapshot()

    assert snapshot["total_recall_requests"] == expected_count
    assert snapshot["total_remember_requests"] == 0
    assert snapshot["recall_latency_sum"] == expected_latency_sum
    assert snapshot["recall_latency_avg_ms"] == (
        expected_latency_sum / expected_count
    )
    assert snapshot["cache_hits"] == 0


def test_api_records_recall_and_remember_requests(tmp_path) -> None:
    """Public API methods record successful and failed request attempts."""
    api = RecallWeaverAPI(str(tmp_path / "observability.sqlite3"))

    assert api.remember_triple("张三", "住在", "杭州")
    results = api.recall("张三", limit=3)
    assert results

    snapshot = api.metrics.get_snapshot()
    assert snapshot["total_remember_requests"] == 1
    assert snapshot["total_recall_requests"] == 1
    assert snapshot["recall_latency_sum"] > 0
    assert snapshot["recall_latency_avg_ms"] > 0

