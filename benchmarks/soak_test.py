"""Run a 30-minute, thread-isolated SQLite WAL soak test.

The default workload uses an isolated ``benchmarks/soak_test.db`` database,
loads 50,000 baseline memories, and then runs ten concurrent clients at an
aggregate target of 100 requests per second with an 80/20 read/write mix.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import random
import sqlite3
import statistics
import sys
import threading
import time
import uuid
from typing import Any

import psutil


EXPECTED_PYTHON = (3, 11, 9)
WORKER_COUNT = 10
TARGET_TPS = 100
READ_RATIO = 0.8
WRITE_INTERVAL = int(round(1.0 / (1.0 - READ_RATIO)))
BASELINE_RECORDS = 50_000
CORE_USER_COUNT = 100
DB_PATH = Path(__file__).resolve().parent / "soak_test.db"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema.sql"
ALLERGENS = ("花生", "牛奶", "海鲜", "鸡蛋", "芒果")
CITIES = ("北京", "上海", "广州", "深圳", "杭州", "成都", "南京", "厦门")
NOISE_TEMPLATES = (
    "群聊闲谈：今天天气不错，适合出门散步。",
    "群聊闲谈：午饭吃了炒饭和青菜，味道很好。",
    "群聊闲谈：周末准备去公园，顺便买些水果。",
    "群聊闲谈：刚看到一部有趣的电影，晚些时候分享。",
    "群聊闲谈：今天路上有点堵，公交晚了几分钟。",
    "群聊闲谈：窗外开始下雨了，回家记得带伞。",
    "群聊闲谈：新开的咖啡店人不多，环境很安静。",
    "群聊闲谈：刚整理完书桌和文件，房间清爽多了。",
)


class SoakTest:
    """Own a file-backed SQLite workload and its thread-local connections."""

    def __init__(self, duration_seconds: int, db_path: Path = DB_PATH) -> None:
        """Initialize workload state without opening or deleting any database.

        Args:
            duration_seconds: Requested duration after baseline setup completes.
            db_path: Dedicated database file used only by this soak run.
        """
        self.duration_seconds = duration_seconds
        self.db_path = db_path
        self.stop_event = threading.Event()
        self.thread_connections = threading.local()
        self.pacing_lock = threading.Lock()
        self.metrics_lock = threading.Lock()
        self.memory_lock = threading.Lock()
        self.next_request_at = 0.0
        self.request_sequence = 0
        self.started_at = 0.0
        self.latencies_ms: list[float] = []
        self.memory_samples: list[tuple[float, float]] = []
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.read_requests = 0
        self.write_requests = 0
        self.lock_conflicts = 0
        self.error_samples: list[str] = []
        self.telemetry_errors: list[str] = []
        self.database_created = False
        self.database_initialized = False

    def connection(self) -> sqlite3.Connection:
        """Return a SQLite connection owned exclusively by the current thread.

        Returns:
            The current thread's lazily opened SQLite connection.

        Raises:
            sqlite3.Error: If SQLite cannot open or configure the connection.
        """
        connection = getattr(self.thread_connections, "connection", None)
        if connection is None:
            connection = sqlite3.connect(
                self.db_path,
                timeout=2.0,
                isolation_level="DEFERRED",
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute("PRAGMA busy_timeout = 2000")
            self.thread_connections.connection = connection
        return connection

    def close_thread_connection(self) -> None:
        """Close the current thread's SQLite handle when its worker exits."""
        connection = getattr(self.thread_connections, "connection", None)
        if connection is not None:
            connection.close()
            self.thread_connections.connection = None

    @staticmethod
    def _utc_timestamp(timestamp: float) -> str:
        """Format a Unix timestamp as a fixed-precision UTC ISO-8601 string."""
        return (
            datetime.fromtimestamp(timestamp, timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )

    def initialize_database(self) -> None:
        """Create the isolated schema, enforce WAL, and load baseline memories.

        Raises:
            FileExistsError: If the dedicated database path already exists.
            OSError: If the schema file cannot be read.
            sqlite3.Error: If SQLite setup or baseline insertion fails.
            RuntimeError: If SQLite does not accept the requested WAL mode.
        """
        if self.db_path.exists():
            raise FileExistsError(
                f"为避免覆盖现有数据，拒绝使用已存在的数据库：{self.db_path}"
            )
        if not SCHEMA_PATH.is_file():
            raise FileNotFoundError(f"找不到 SQLite schema：{SCHEMA_PATH}")

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.database_created = True
        connection = self.connection()
        journal_mode = str(
            connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        ).lower()
        if journal_mode != "wal":
            raise RuntimeError(f"无法启用 SQLite WAL 模式：{journal_mode}")

        connection.execute("PRAGMA synchronous = NORMAL")
        synchronous_mode = int(
            connection.execute("PRAGMA synchronous").fetchone()[0]
        )
        if synchronous_mode != 1:
            raise RuntimeError(
                f"SQLite synchronous 应为 NORMAL(1)，实际为 {synchronous_mode}"
            )

        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        connection.executescript(schema_sql)
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_soak_entities_tenant_name
            ON entities(tenant_id, name)
            """
        )
        self._insert_baseline(connection)
        self.database_initialized = True

    def _insert_baseline(self, connection: sqlite3.Connection) -> None:
        """Insert 100 allergy/location profiles and 49,800 chatter memories.

        Args:
            connection: Main-thread connection used only during setup.

        Raises:
            AssertionError: If the expected 50,000 baseline rows are not stored.
            sqlite3.Error: If a tenant, entity, memory, or edge insert fails.
        """
        now = int(time.time())
        now_timestamp = self._utc_timestamp(time.time())
        entity_ids: dict[str, str] = {}
        profile_memory_ids: dict[tuple[str, str], str] = {}

        with connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO tenants (id, name, created_at)
                VALUES (?, ?, ?)
                """,
                ("default", "Soak Test Tenant", now),
            )

            entity_names: set[str] = set()
            for user_number in range(1, CORE_USER_COUNT + 1):
                entity_names.add(f"user_{user_number}")
                entity_names.add(ALLERGENS[(user_number - 1) % len(ALLERGENS)])
            entity_names.update(CITIES)
            for name in sorted(entity_names):
                entity_id = str(uuid.uuid4())
                entity_ids[name] = entity_id
                connection.execute(
                    """
                    INSERT INTO entities (
                        id, tenant_id, name, canonical_name, entity_type, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entity_id,
                        "default",
                        name,
                        name,
                        "user" if name.startswith("user_") else "concept",
                        now,
                    ),
                )

            profile_rows: list[tuple[Any, ...]] = []
            edge_rows: list[tuple[Any, ...]] = []
            for user_number in range(1, CORE_USER_COUNT + 1):
                user_name = f"user_{user_number}"
                allergen = ALLERGENS[(user_number - 1) % len(ALLERGENS)]
                facts = (
                    ("过敏源", allergen, f"{user_name} 对{allergen}过敏。"),
                    ("居住地", "北京", f"{user_name} 目前居住在北京。"),
                )
                for predicate, object_name, content in facts:
                    memory_id = str(uuid.uuid4())
                    profile_memory_ids[(user_name, predicate)] = memory_id
                    profile_rows.append(
                        (
                            memory_id,
                            "default",
                            content,
                            "fact",
                            1.0,
                            1.0,
                            2.0,
                            0.01,
                            0,
                            now,
                            2.0,
                            now,
                            None,
                            now,
                            "active",
                            now,
                        )
                    )
                    edge_rows.append(
                        (
                            str(uuid.uuid4()),
                            "default",
                            entity_ids[user_name],
                            predicate,
                            entity_ids[object_name],
                            memory_id,
                            now_timestamp,
                            None,
                            1.0,
                            now,
                        )
                    )

            connection.executemany(
                """
                INSERT INTO memories (
                    id, tenant_id, content, memory_type, instruction_weight,
                    emotion_weight, base_weight, decay_lambda, retrieval_count,
                    last_decay_at, decayed_weight, valid_from, valid_to, tx_time,
                    status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                profile_rows,
            )
            connection.executemany(
                """
                INSERT INTO edges (
                    id, tenant_id, subject_id, predicate, object_id, memory_id,
                    valid_from, valid_to, confidence, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                edge_rows,
            )

            noise_count = BASELINE_RECORDS - len(profile_rows)
            noise_rows = (
                (
                    str(uuid.uuid4()),
                    "default",
                    (
                        f"{NOISE_TEMPLATES[index % len(NOISE_TEMPLATES)]} "
                        f"群聊消息编号 {index + 1}。"
                    ),
                    "conversation",
                    1.0,
                    1.0,
                    0.1,
                    0.01,
                    0,
                    now,
                    0.1,
                    now,
                    None,
                    now,
                    "active",
                    now,
                )
                for index in range(noise_count)
            )
            connection.executemany(
                """
                INSERT INTO memories (
                    id, tenant_id, content, memory_type, instruction_weight,
                    emotion_weight, base_weight, decay_lambda, retrieval_count,
                    last_decay_at, decayed_weight, valid_from, valid_to, tx_time,
                    status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                noise_rows,
            )

        actual_count = int(
            connection.execute("SELECT count(*) FROM memories").fetchone()[0]
        )
        if actual_count != BASELINE_RECORDS:
            raise AssertionError(
                f"基线数据应为 {BASELINE_RECORDS} 条，实际为 {actual_count} 条"
            )

    def _reserve_request_slot(self) -> int | None:
        """Pace aggregate request starts at the configured global TPS.

        Returns:
            A unique monotonically increasing request sequence, or ``None`` if
            shutdown begins before this worker's scheduled request.
        """
        with self.pacing_lock:
            now = time.perf_counter()
            scheduled_at = max(now, self.next_request_at)
            self.next_request_at = scheduled_at + 1.0 / TARGET_TPS
        if scheduled_at > now and self.stop_event.wait(scheduled_at - now):
            return None
        if self.stop_event.is_set():
            return None
        with self.metrics_lock:
            request_id = self.request_sequence
            self.request_sequence += 1
        return request_id

    def recall(self, connection: sqlite3.Connection, user_number: int) -> None:
        """Execute text-index and current-graph retrieval for one synthetic user.

        Args:
            connection: SQLite handle owned by this worker thread.
            user_number: Profile selected for this mixed-recall request.

        Raises:
            sqlite3.Error: If either text or graph retrieval fails.
        """
        user_name = f"user_{user_number}"
        fts_query = f'"{user_name}"* OR "过敏"*'
        connection.execute(
            """
            SELECT memory.id, memory.content, memory.base_weight
            FROM memories_fts
            JOIN memories AS memory ON memory.rowid = memories_fts.rowid
            WHERE memories_fts MATCH ?
              AND memory.tenant_id = ?
              AND memory.status = 'active'
            ORDER BY bm25(memories_fts), memory.base_weight DESC, memory.id
            LIMIT 5
            """,
            (fts_query, "default"),
        ).fetchall()
        connection.execute(
            """
            SELECT edge.predicate, object.name, edge.valid_from
            FROM edges AS edge
            JOIN entities AS subject
              ON subject.id = edge.subject_id
             AND subject.tenant_id = edge.tenant_id
            JOIN entities AS object
              ON object.id = edge.object_id
             AND object.tenant_id = edge.tenant_id
            WHERE edge.tenant_id = ?
              AND subject.name = ?
              AND edge.valid_to IS NULL
            ORDER BY edge.predicate
            """,
            ("default", user_name),
        ).fetchall()

    def remember(
        self,
        connection: sqlite3.Connection,
        randomizer: random.Random,
        user_number: int,
    ) -> None:
        """Write chatter or atomically advance a user's residence fact.

        Conflict updates are selected randomly for at least 60% of write
        requests. The prior edge is closed and the new memory/edge are inserted
        in a single immediate SQLite transaction.

        Args:
            connection: SQLite handle owned by this worker thread.
            randomizer: Per-worker pseudo-random source.
            user_number: Profile selected for this write request.

        Raises:
            AssertionError: If a selected current residence is missing or fails
                to close exactly once.
            sqlite3.Error: If an atomic write cannot be committed.
        """
        if randomizer.random() >= 0.6:
            now = int(time.time())
            chatter = (
                f"{NOISE_TEMPLATES[randomizer.randrange(len(NOISE_TEMPLATES))]} "
                f"并发写入 {uuid.uuid4().hex[:12]}。"
            )
            with connection:
                connection.execute(
                    """
                    INSERT INTO memories (
                        id, tenant_id, content, memory_type, instruction_weight,
                        emotion_weight, base_weight, decay_lambda,
                        retrieval_count, last_decay_at, decayed_weight, valid_from,
                        valid_to, tx_time, status, created_at
                    )
                    VALUES (?, ?, ?, ?, 1.0, 1.0, 0.1, 0.01, 0, ?, 0.1,
                            ?, NULL, ?, 'active', ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        "default",
                        chatter,
                        "conversation",
                        now,
                        now,
                        now,
                        now,
                    ),
                )
            return

        user_name = f"user_{user_number}"
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                """
                SELECT edge.id AS edge_id, edge.valid_from,
                       subject.id AS subject_id, object.name AS city
                FROM edges AS edge
                JOIN entities AS subject
                  ON subject.id = edge.subject_id
                 AND subject.tenant_id = edge.tenant_id
                JOIN entities AS object
                  ON object.id = edge.object_id
                 AND object.tenant_id = edge.tenant_id
                WHERE edge.tenant_id = ?
                  AND subject.name = ?
                  AND edge.predicate = ?
                  AND edge.valid_to IS NULL
                """,
                ("default", user_name, "居住地"),
            ).fetchone()
            if current is None:
                raise AssertionError(f"{user_name} 缺少当前居住地事实")

            candidates = [city for city in CITIES if city != current["city"]]
            city = randomizer.choice(candidates)
            latest_start = datetime.fromisoformat(
                str(current["valid_from"]).replace("Z", "+00:00")
            )
            now_datetime = datetime.now(timezone.utc)
            if now_datetime <= latest_start:
                now_datetime = latest_start + timedelta(microseconds=1)
            valid_from = now_datetime.isoformat(
                timespec="microseconds"
            ).replace("+00:00", "Z")
            now_epoch = int(now_datetime.timestamp())

            object_row = connection.execute(
                """
                SELECT id
                FROM entities
                WHERE tenant_id = ? AND name = ?
                ORDER BY id
                LIMIT 1
                """,
                ("default", city),
            ).fetchone()
            if object_row is None:
                raise AssertionError(f"预置城市实体不存在：{city}")

            memory_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO memories (
                    id, tenant_id, content, memory_type, instruction_weight,
                    emotion_weight, base_weight, decay_lambda, retrieval_count,
                    last_decay_at, decayed_weight, valid_from, valid_to, tx_time,
                    status, created_at
                )
                VALUES (?, ?, ?, 'fact', 1.0, 1.0, 1.5, 0.01, 0, ?, 1.5,
                        ?, NULL, ?, 'active', ?)
                """,
                (
                    memory_id,
                    "default",
                    f"{user_name} 搬家后居住地更新为{city}。",
                    now_epoch,
                    now_epoch,
                    now_epoch,
                    now_epoch,
                ),
            )
            update = connection.execute(
                """
                UPDATE edges
                SET valid_to = ?
                WHERE id = ? AND valid_to IS NULL
                """,
                (valid_from, current["edge_id"]),
            )
            if update.rowcount != 1:
                raise AssertionError(
                    f"{user_name} 的当前居住地边未能原子关闭"
                )
            connection.execute(
                """
                INSERT INTO edges (
                    id, tenant_id, subject_id, predicate, object_id, memory_id,
                    valid_from, valid_to, confidence, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 1.0, ?)
                """,
                (
                    str(uuid.uuid4()),
                    "default",
                    current["subject_id"],
                    "居住地",
                    object_row["id"],
                    memory_id,
                    valid_from,
                    now_epoch,
                ),
            )

    def _record_result(
        self,
        *,
        succeeded: bool,
        is_write: bool,
        latency_ms: float,
        error: Exception | None = None,
    ) -> None:
        """Update request counters and preserve lock errors separately."""
        with self.metrics_lock:
            self.total_requests += 1
            if is_write:
                self.write_requests += 1
            else:
                self.read_requests += 1
            self.latencies_ms.append(latency_ms)
            if succeeded:
                self.successful_requests += 1
            else:
                self.failed_requests += 1
                if isinstance(error, sqlite3.OperationalError) and (
                    "database is locked" in str(error).lower()
                ):
                    self.lock_conflicts += 1
                if error is not None and len(self.error_samples) < 10:
                    self.error_samples.append(
                        f"{type(error).__name__}: {error}"
                    )

    def worker(self, worker_number: int) -> None:
        """Run one persistent client loop with its own SQLite connection.

        Args:
            worker_number: Stable index used to derive this worker's RNG seed.
        """
        randomizer = random.Random(20261031 + worker_number)
        try:
            connection = self.connection()
        except Exception as error:
            self._record_result(
                succeeded=False,
                is_write=False,
                latency_ms=0.0,
                error=error,
            )
            return

        try:
            while not self.stop_event.is_set():
                request_id = self._reserve_request_slot()
                if request_id is None:
                    break

                is_write = request_id % WRITE_INTERVAL == WRITE_INTERVAL - 1
                started = time.perf_counter()
                caught_error: Exception | None = None
                succeeded = False
                try:
                    user_number = randomizer.randint(1, CORE_USER_COUNT)
                    if is_write:
                        self.remember(connection, randomizer, user_number)
                    else:
                        self.recall(connection, user_number)
                    succeeded = True
                except sqlite3.OperationalError as error:
                    caught_error = error
                except Exception as error:
                    caught_error = error
                finally:
                    elapsed_ms = (time.perf_counter() - started) * 1_000
                    self._record_result(
                        succeeded=succeeded,
                        is_write=is_write,
                        latency_ms=elapsed_ms,
                        error=caught_error,
                    )
        finally:
            try:
                self.close_thread_connection()
            except sqlite3.Error as error:
                with self.metrics_lock:
                    if len(self.error_samples) < 10:
                        self.error_samples.append(
                            f"SQLite connection close: {error}"
                        )

    def sample_memory(self, elapsed_seconds: float) -> None:
        """Record process RSS at a scheduled telemetry point.

        Args:
            elapsed_seconds: Elapsed test time represented by this sample.
        """
        try:
            rss_mb = psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
        except (psutil.Error, OSError) as error:
            with self.memory_lock:
                self.telemetry_errors.append(
                    f"RSS sample failed: {type(error).__name__}: {error}"
                )
            return
        with self.memory_lock:
            self.memory_samples.append((elapsed_seconds, rss_mb))

    def _snapshot(self) -> tuple[int, int, int, int, int, list[float]]:
        """Return one internally consistent copy of request metrics."""
        with self.metrics_lock:
            return (
                self.total_requests,
                self.successful_requests,
                self.failed_requests,
                self.read_requests,
                self.write_requests,
                list(self.latencies_ms),
            )

    @staticmethod
    def _percentile(values: list[float], percentile: int) -> float:
        """Compute a deterministic nearest-rank percentile in milliseconds."""
        if not values:
            return 0.0
        ordered = sorted(values)
        rank = max(1, (percentile * len(ordered) + 99) // 100)
        return ordered[rank - 1]

    @classmethod
    def latency_summary(cls, values: list[float]) -> dict[str, float]:
        """Compute average, P50/P90/P95/P99, and max latency.

        Args:
            values: Request latencies, in milliseconds.

        Returns:
            A summary mapping whose percentile values use nearest-rank
            calculation, including exact observed minimum/maximum samples.
        """
        if not values:
            return {
                "Avg": 0.0,
                "P50": 0.0,
                "P90": 0.0,
                "P95": 0.0,
                "P99": 0.0,
                "Max": 0.0,
            }
        return {
            "Avg": statistics.fmean(values),
            "P50": cls._percentile(values, 50),
            "P90": cls._percentile(values, 90),
            "P95": cls._percentile(values, 95),
            "P99": cls._percentile(values, 99),
            "Max": max(values),
        }

    def print_dashboard(self, elapsed_seconds: float, delta_tps: float) -> None:
        """Refresh the required single-line progress display."""
        total, _, _, reads, writes, latencies = self._snapshot()
        recent_p99 = self._percentile(latencies[-1_000:], 99)
        minutes = int(elapsed_seconds) // 60
        seconds = int(elapsed_seconds) % 60
        with self.metrics_lock:
            lock_conflicts = self.lock_conflicts
        with self.memory_lock:
            memory_mb = (
                self.memory_samples[-1][1] if self.memory_samples else 0.0
            )
        sys.stdout.write(
            f"\r[{minutes:02d}:{seconds:02d}] TPS: {delta_tps:5.1f} | "
            f"写入: {writes} | 检索: {reads} | 内存: {memory_mb:.1f} MB | "
            f"P99延迟: {recent_p99:.2f} ms | 锁冲突: {lock_conflicts}"
        )
        sys.stdout.flush()

    def validate_consistency(self) -> int:
        """Run exact active-edge and foreign-key consistency checks.

        Returns:
            Number of persisted memories after the soak workload.

        Raises:
            RuntimeError: If concurrent writes create duplicate current edges.
            sqlite3.Error: If the final SQL validation cannot run.
        """
        connection = self.connection()
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
            raise RuntimeError("双时间戳在并发写入下被击穿！")

        foreign_key_violations = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        if foreign_key_violations:
            raise RuntimeError(
                f"长稳测试发现外键完整性问题：{foreign_key_violations[:5]}"
            )

        return int(
            connection.execute("SELECT count(*) FROM memories").fetchone()[0]
        )

    def _memory_growth(self) -> tuple[float | None, float | None, str]:
        """Compare first/last minute RSS averages, with short-run fallback."""
        with self.memory_lock:
            samples = list(self.memory_samples)
        if len(samples) < 2:
            return None, None, "内存采样点不足，无法计算增长率。"

        if self.duration_seconds >= 120:
            first_window = [rss for elapsed, rss in samples if elapsed < 60]
            last_window = [
                rss
                for elapsed, rss in samples
                if elapsed >= self.duration_seconds - 60
            ]
        else:
            first_window = [samples[0][1]]
            last_window = [samples[-1][1]]
        if not first_window or not last_window:
            return None, None, "首分钟或末分钟内无 RSS 样本。"

        first_average = statistics.fmean(first_window)
        last_average = statistics.fmean(last_window)
        growth_mb = last_average - first_average
        growth_percent = (
            growth_mb / first_average * 100 if first_average > 0 else 0.0
        )
        return first_average, growth_percent, (
            f"首窗口 {first_average:.1f} MB，末窗口 {last_average:.1f} MB，"
            f"变化 {growth_mb:+.1f} MB ({growth_percent:+.1f}%)。"
        )

    def print_report(
        self,
        elapsed_seconds: float,
        persisted_records: int,
        interrupted: bool,
    ) -> None:
        """Print the final Markdown soak report and any explicit warnings."""
        total, successful, failed, reads, writes, latencies = self._snapshot()
        with self.metrics_lock:
            lock_conflicts = self.lock_conflicts
            errors = list(self.error_samples)
        summary = self.latency_summary(latencies)
        success_rate = successful / total * 100 if total else 0.0
        first_memory, growth_percent, memory_text = self._memory_growth()
        p99_status = "优秀" if summary["P99"] < 50.0 else "未达标"
        run_status = "已中断（已优雅停止）" if interrupted else "完成"

        print("\n\n# 《1800秒长稳浸泡压测报告》")
        print()
        print("| 项目 | 结果 |")
        print("|---|---:|")
        print(f"| 运行状态 | {run_status} |")
        print(f"| 实际运行时长 | {elapsed_seconds:.2f} 秒 |")
        print(f"| 基线记录数 | {BASELINE_RECORDS:,} |")
        print(f"| 最终总记录数 | {persisted_records:,} |")
        print(f"| 总请求数 | {total:,} |")
        print(f"| 成功 / 失败 | {successful:,} / {failed:,} |")
        print(f"| 成功率 | {success_rate:.3f}% |")
        print(f"| 检索 / 写入请求 | {reads:,} / {writes:,} |")
        print(f"| 数据库锁冲突次数 | {lock_conflicts:,} |")
        print(f"| RSS 首末窗口比较 | {memory_text} |")
        print(f"| 延迟 P99 目标（< 50 ms） | {p99_status} |")
        print()
        print("| 延迟指标 | 毫秒 |")
        print("|---|---:|")
        for label in ("Avg", "P50", "P90", "P95", "P99", "Max"):
            print(f"| {label} | {summary[label]:.3f} |")

        if growth_percent is not None and growth_percent > 20:
            print()
            print(
                f"🔴 **内存增长警告：首末窗口 RSS 增幅 "
                f"{growth_percent:.1f}%，超过 20%。**"
            )
        elif first_memory is not None:
            print()
            print(f"内存增长阈值检查：未超过 20%。")
        if errors:
            print()
            print("### 采样错误（最多展示 10 项）")
            for error in errors:
                print(f"- `{error}`")
        with self.memory_lock:
            telemetry_errors = list(self.telemetry_errors)
        if telemetry_errors:
            print()
            print("### 遥测错误")
            for error in telemetry_errors:
                print(f"- `{error}`")

    def cleanup(self) -> None:
        """Close the main-thread connection and remove only this run's files."""
        try:
            self.close_thread_connection()
        except sqlite3.Error as error:
            print(f"数据库连接关闭失败：{error}", file=sys.stderr)
        if self.database_created:
            for path in (
                self.db_path,
                Path(f"{self.db_path}-wal"),
                Path(f"{self.db_path}-shm"),
            ):
                try:
                    path.unlink(missing_ok=True)
                except OSError as error:
                    print(f"临时数据库清理失败 {path}: {error}", file=sys.stderr)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line options for this standalone benchmark.

    Args:
        argv: Optional explicit argument list, useful for automated checks.

    Returns:
        Parsed command-line options.
    """
    parser = argparse.ArgumentParser(
        description="Run the RecallWeaver SQLite WAL soak test."
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=1_800,
        help="Soak duration in seconds after baseline setup (default: 1800).",
    )
    args = parser.parse_args(argv)
    if args.duration < 1:
        parser.error("--duration 必须是大于 0 的整数")
    return args


def main(argv: list[str] | None = None) -> int:
    """Run setup, concurrent workload, consistency checks, report, and cleanup.

    Args:
        argv: Optional command-line arguments.

    Returns:
        Zero after a complete or gracefully interrupted run.

    Raises:
        RuntimeError: If the final database consistency assertion fails.
        FileExistsError: If the isolated soak database already exists.
    """
    if sys.version_info[:3] != EXPECTED_PYTHON:
        raise RuntimeError(
            "该压测严格要求 Python 3.11.9，当前版本为 "
            f"{sys.version_info.major}.{sys.version_info.minor}."
            f"{sys.version_info.micro}"
        )

    args = parse_args(argv)
    soak = SoakTest(duration_seconds=args.duration)
    executor: ThreadPoolExecutor | None = None
    futures = []
    interrupted = False
    fatal_error: Exception | None = None
    started_at = time.perf_counter()
    elapsed_seconds = 0.0
    persisted_records = 0

    try:
        print(
            f"准备独立 WAL 数据库并写入 {BASELINE_RECORDS:,} 条基线记忆："
            f"{soak.db_path}"
        )
        soak.initialize_database()
        soak.started_at = time.perf_counter()
        started_at = soak.started_at
        soak.sample_memory(0.0)

        executor = ThreadPoolExecutor(
            max_workers=WORKER_COUNT,
            thread_name_prefix="recallweaver-soak",
        )
        futures = [
            executor.submit(soak.worker, worker_number)
            for worker_number in range(WORKER_COUNT)
        ]
        workload_started_at = time.perf_counter()
        next_dashboard_at = workload_started_at + 1.0
        next_sample_at = workload_started_at + 10.0
        previous_tps_at = workload_started_at
        previous_request_count = 0
        deadline = workload_started_at + args.duration

        while not soak.stop_event.is_set():
            now = time.perf_counter()
            if now >= deadline:
                break

            elapsed = now - started_at
            if now >= next_sample_at:
                soak.sample_memory(elapsed)
                next_sample_at = now + 10.0
            if now >= next_dashboard_at:
                request_count = soak._snapshot()[0]
                interval = max(now - previous_tps_at, 0.001)
                delta_tps = (request_count - previous_request_count) / interval
                soak.print_dashboard(elapsed, delta_tps)
                previous_request_count = request_count
                previous_tps_at = now
                next_dashboard_at = now + 1.0
            time.sleep(0.05)
    except KeyboardInterrupt:
        interrupted = True
        soak.stop_event.set()
        print("\n收到 Ctrl+C，正在停止 worker 并生成当前报告……")
    except Exception as error:
        fatal_error = error
        soak.stop_event.set()
    finally:
        soak.stop_event.set()
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

        elapsed_seconds = max(0.0, time.perf_counter() - started_at)
        if soak.database_created:
            soak.sample_memory(elapsed_seconds)
        if soak.database_initialized:
            try:
                persisted_records = soak.validate_consistency()
            except Exception as error:
                fatal_error = fatal_error or error

        soak.print_report(
            elapsed_seconds=elapsed_seconds,
            persisted_records=persisted_records,
            interrupted=interrupted,
        )
        soak.cleanup()

    if fatal_error is not None:
        raise fatal_error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
