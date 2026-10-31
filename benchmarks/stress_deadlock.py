"""Exercise SQLite transaction retry and temporal conflict handling at 50 threads."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import random
import sqlite3
import sys
import threading
import time
import tracemalloc
from typing import Any
import uuid

from recallweaver.api import RecallWeaverAPI
from recallweaver.errors import DatabaseError


WORKER_COUNT = 50
DEFAULT_DURATION_SECONDS = 300
DATABASE_PATH = Path(__file__).resolve().parent / "stress_deadlock.db"
CITIES = ("北京", "上海", "广州", "深圳", "杭州", "成都", "南京", "厦门")


class StressMetrics:
    """Thread-safe counters and bounded error samples for the stress run."""

    def __init__(self) -> None:
        """Initialize synchronized workload counters."""
        self.lock = threading.Lock()
        self.completed = 0
        self.failed = 0
        self.lock_conflicts = 0
        self.retry_attempts = 0
        self.errors: list[str] = []

    def record_success(self) -> None:
        """Count one operation that completed successfully."""
        with self.lock:
            self.completed += 1

    def record_error(self, error: Exception) -> None:
        """Count an operation failure and identify wrapped lock errors."""
        with self.lock:
            self.failed += 1
            if _has_locked_operational_error(error):
                self.lock_conflicts += 1
            if len(self.errors) < 10:
                self.errors.append(f"{type(error).__name__}: {error}")

    def snapshot(self) -> tuple[int, int, int, list[str]]:
        """Return a consistent copy of counters and sample errors."""
        with self.lock:
            return (
                self.completed,
                self.failed,
                self.lock_conflicts,
                list(self.errors),
            )

    def add_retry_attempts(self, count: int) -> None:
        """Accumulate database-level lock retries."""
        with self.lock:
            self.retry_attempts = count


def _has_locked_operational_error(error: BaseException) -> bool:
    """Walk wrapped exceptions and find an SQLite database-lock failure."""
    current: BaseException | None = error
    while current is not None:
        if (
            isinstance(current, sqlite3.OperationalError)
            and "database is locked" in str(current).lower()
        ):
            return True
        current = current.__cause__
    return False


def _worker(
    worker_id: int,
    api: RecallWeaverAPI,
    start_event: threading.Event,
    stop_event: threading.Event,
    metrics: StressMetrics,
) -> None:
    """Run one client's strict 40/20/40 request cycle until stop is set.

    Args:
        worker_id: Stable worker index for unique writes and deterministic city
            selection.
        api: Shared API whose database operations create independent SQLite
            connections.
        start_event: Barrier released once all workers have been submitted.
        stop_event: Event set when the requested duration expires.
        metrics: Shared synchronized success and error counters.
    """
    randomizer = random.Random(20261031 + worker_id)
    operation_index = worker_id % 5
    if not start_event.wait(timeout=30):
        metrics.record_error(TimeoutError("worker start barrier timed out"))
        return

    while not stop_event.is_set():
        operation_kind = operation_index % 5
        try:
            if operation_kind in (0, 1):
                api.add_memory(
                    (
                        f"stress worker {worker_id} event "
                        f"{operation_index} {uuid.uuid4().hex}"
                    )
                )
            elif operation_kind == 2:
                city = CITIES[
                    (operation_index // 5 + worker_id + randomizer.randrange(
                        len(CITIES)
                    ))
                    % len(CITIES)
                ]
                api.memory_manager.remember_with_conflict_resolution(
                    "stress_shared_user",
                    "住在",
                    city,
                )
            else:
                results = api.recall(
                    "stress_shared_user 居住地 并发记忆",
                    limit=5,
                )
                if not isinstance(results, list):
                    raise AssertionError("recall 必须返回列表")
            metrics.record_success()
        except sqlite3.OperationalError as error:
            metrics.record_error(error)
        except DatabaseError as error:
            metrics.record_error(error)
        except Exception as error:
            metrics.record_error(error)
        finally:
            operation_index += 1


def _print_dashboard(
    elapsed_seconds: float,
    memory_mb: float,
    completed: int,
    lock_conflicts: int,
) -> None:
    """Print the required ten-second status line."""
    sys.stdout.write(
        f"\r运行 {elapsed_seconds:6.1f} 秒 | "
        f"内存 {memory_mb:7.1f} MB | "
        f"累计执行 {completed:,} 次 | "
        f"锁冲突 {lock_conflicts:,} 次"
    )
    sys.stdout.flush()


def run_stress_test(
    duration_seconds: int,
    database_path: Path = DATABASE_PATH,
) -> dict[str, Any]:
    """Initialize a dedicated WAL database and run the 50-client stress test.

    Args:
        duration_seconds: Workload duration in seconds.
        database_path: Dedicated database file, removed after the run.

    Returns:
        Summary counters and consistency results.

    Raises:
        FileExistsError: If the dedicated database already exists.
        AssertionError: If temporal current-edge invariants are violated.
        RuntimeError: If any worker operation failed.
        sqlite3.Error: If setup or final consistency checks fail.
    """
    if database_path.exists():
        raise FileExistsError(
            f"拒绝覆盖已存在的压测数据库：{database_path}"
        )

    database_path.parent.mkdir(parents=True, exist_ok=True)
    database_created = False
    api: RecallWeaverAPI | None = None
    start_event = threading.Event()
    stop_event = threading.Event()
    metrics = StressMetrics()
    tracemalloc.start()
    started_at = time.perf_counter()
    fatal_error: Exception | None = None
    futures = []
    executor: ThreadPoolExecutor | None = None
    summary: dict[str, Any] = {}

    try:
        setup_connection = sqlite3.connect(database_path, timeout=1.0)
        try:
            mode = str(
                setup_connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            ).lower()
            if mode != "wal":
                raise RuntimeError(f"未能启用 WAL，实际模式为 {mode}")
            setup_connection.execute("PRAGMA synchronous = NORMAL")
            setup_connection.execute("PRAGMA busy_timeout = 1000")
            setup_connection.commit()
        finally:
            setup_connection.close()
        database_created = True

        api = RecallWeaverAPI(str(database_path))
        api.remember_triple("stress_shared_user", "住在", "北京")
        executor = ThreadPoolExecutor(
            max_workers=WORKER_COUNT,
            thread_name_prefix="recallweaver-deadlock",
        )
        futures = [
            executor.submit(
                _worker,
                worker_id,
                api,
                start_event,
                stop_event,
                metrics,
            )
            for worker_id in range(WORKER_COUNT)
        ]

        started_at = time.perf_counter()
        deadline = started_at + duration_seconds
        start_event.set()
        next_report_at = started_at + 10.0
        while time.perf_counter() < deadline:
            now = time.perf_counter()
            if now >= next_report_at:
                completed, _, lock_conflicts, _ = metrics.snapshot()
                current_bytes, _ = tracemalloc.get_traced_memory()
                _print_dashboard(
                    now - started_at,
                    current_bytes / (1024 * 1024),
                    completed,
                    lock_conflicts,
                )
                next_report_at = now + 10.0
            time.sleep(min(0.1, max(0.0, deadline - now)))
    except KeyboardInterrupt:
        stop_event.set()
        start_event.set()
        print("\n收到 Ctrl+C，正在停止所有压力线程……")
    except Exception as error:
        fatal_error = error
        stop_event.set()
        start_event.set()
    finally:
        stop_event.set()
        start_event.set()
        if executor is not None:
            try:
                executor.shutdown(wait=True, cancel_futures=True)
            except Exception as error:
                fatal_error = fatal_error or error

        for future in futures:
            try:
                future.result()
            except Exception as error:
                fatal_error = fatal_error or error

        if api is not None and database_created:
            try:
                with api.database_manager.get_connection() as connection:
                    duplicates = connection.execute(
                        """
                        SELECT subject_id, predicate, count(*)
                        FROM edges
                        WHERE valid_to IS NULL
                        GROUP BY subject_id, predicate
                        HAVING count(*) > 1
                        """
                    ).fetchall()
                    if duplicates:
                        raise AssertionError(
                            "并发冲突后发现多条有效事实边："
                            f"{[tuple(row) for row in duplicates]}"
                        )
                    foreign_key_errors = connection.execute(
                        "PRAGMA foreign_key_check"
                    ).fetchall()
                    if foreign_key_errors:
                        raise AssertionError(
                            f"外键完整性检查失败：{foreign_key_errors[:5]}"
                        )
                    memory_count = int(
                        connection.execute(
                            "SELECT count(*) FROM memories"
                        ).fetchone()[0]
                    )
                    edge_count = int(
                        connection.execute(
                            "SELECT count(*) FROM edges"
                        ).fetchone()[0]
                    )
            except Exception as error:
                fatal_error = fatal_error or error
                memory_count = 0
                edge_count = 0
        else:
            memory_count = 0
            edge_count = 0

        elapsed = max(0.0, time.perf_counter() - started_at)
        completed, failed, lock_conflicts, errors = metrics.snapshot()
        if api is not None:
            metrics.add_retry_attempts(api.database_manager.retry_attempts)
        current_bytes, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        success_rate = (
            completed / (completed + failed) * 100
            if completed + failed
            else 0.0
        )
        sys.stdout.write("\n\n")
        print("# 极限并发死锁压测报告")
        print()
        print("| 指标 | 结果 |")
        print("|---|---:|")
        print(f"| 实际运行时间 | {elapsed:.2f} 秒 |")
        print(f"| 并发 Worker | {WORKER_COUNT} |")
        print(f"| 总完成操作 | {completed:,} |")
        print(f"| 失败操作 | {failed:,} |")
        print(f"| 成功率 | {success_rate:.3f}% |")
        print(f"| 最终未恢复锁冲突 | {lock_conflicts:,} |")
        print(f"| 指数退避重试次数 | {metrics.retry_attempts:,} |")
        print(f"| 最终记忆 / 边记录 | {memory_count:,} / {edge_count:,} |")
        print(f"| 当前 / 峰值 Python 堆内存 | "
              f"{current_bytes / (1024 * 1024):.1f} / "
              f"{peak_bytes / (1024 * 1024):.1f} MB |")
        print()
        if errors:
            print("### 失败样例（最多展示 10 项）")
            for error in errors:
                print(f"- `{error}`")
        if not errors:
            print("所有 worker 操作均成功；当前事实边与外键校验通过。")

        summary = {
            "elapsed_seconds": elapsed,
            "completed": completed,
            "failed": failed,
            "lock_conflicts": lock_conflicts,
            "retry_attempts": metrics.retry_attempts,
            "memory_count": memory_count,
            "edge_count": edge_count,
            "success_rate": success_rate,
        }

        if database_created:
            for path in (
                database_path,
                Path(f"{database_path}-wal"),
                Path(f"{database_path}-shm"),
            ):
                try:
                    path.unlink(missing_ok=True)
                except OSError as error:
                    print(f"临时数据库清理失败 {path}: {error}", file=sys.stderr)

    if fatal_error is not None:
        raise fatal_error
    if summary["failed"] > 0:
        raise RuntimeError(
            f"并发压测存在 {summary['failed']} 个失败操作，详见报告"
        )
    return summary


def main(argv: list[str] | None = None) -> int:
    """Parse duration options and execute the isolated concurrency test."""
    parser = argparse.ArgumentParser(
        description="Run RecallWeaver's 50-thread SQLite lock stress test."
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=DEFAULT_DURATION_SECONDS,
        help="Stress duration in seconds (default: 300).",
    )
    args = parser.parse_args(argv)
    if args.duration < 1:
        parser.error("--duration 必须是大于 0 的整数")
    summary = run_stress_test(args.duration)
    if summary["lock_conflicts"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
