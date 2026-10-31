"""Thread-safe in-memory API request metrics."""

from __future__ import annotations

import math
import threading


class MetricsCollector:
    """Collect aggregate request counters and recall latency without races."""

    def __init__(self) -> None:
        """Initialize request totals and latency accumulator to zero."""
        self._lock = threading.Lock()
        self._total_recall_requests = 0
        self._total_remember_requests = 0
        self._recall_latency_sum = 0.0
        self._cache_hits = 0

    def record_recall(self, duration_ms: float) -> None:
        """Record one recall attempt and its elapsed time.

        Args:
            duration_ms: Non-negative finite elapsed duration in milliseconds.

        Raises:
            TypeError: If the duration is not numeric or is a boolean.
            ValueError: If the duration is negative or not finite.
        """
        if isinstance(duration_ms, bool) or not isinstance(
            duration_ms, (int, float)
        ):
            raise TypeError("duration_ms 必须是数值")
        if not math.isfinite(duration_ms) or duration_ms < 0:
            raise ValueError("duration_ms 必须是有限的非负数")

        with self._lock:
            self._total_recall_requests += 1
            self._recall_latency_sum += float(duration_ms)

    def record_remember(self) -> None:
        """Record one remember-triple attempt."""
        with self._lock:
            self._total_remember_requests += 1

    def get_snapshot(self) -> dict[str, int | float]:
        """Return a consistent copy of all current metrics.

        Returns:
            A snapshot with request counts, accumulated latency, average latency,
            and cache hits.
        """
        with self._lock:
            recall_requests = self._total_recall_requests
            latency_sum = self._recall_latency_sum
            return {
                "total_recall_requests": recall_requests,
                "total_remember_requests": self._total_remember_requests,
                "recall_latency_sum": latency_sum,
                "recall_latency_avg_ms": (
                    latency_sum / recall_requests if recall_requests else 0.0
                ),
                "cache_hits": self._cache_hits,
            }
