"""Measure trigram-backed Chinese retrieval against an isolated 100k corpus."""

from __future__ import annotations

from pathlib import Path
import statistics
import tempfile
import time
import uuid

from recallweaver.db import Database
from recallweaver.retrieval import Retriever


DATASET_SIZE = 100_000
QUERY = "杭州小笼包"
TARGET_CONTENT = "我今天去杭州西湖吃了小笼包"
REPETITIONS = 20
BATCH_SIZE = 5_000


def _insert_benchmark_corpus(database: Database) -> str:
    """Create exactly 100,000 recent memories in an isolated database.

    Args:
        database: Initialized temporary benchmark database.

    Returns:
        ID of the sole memory containing the target Chinese evidence.
    """
    now = int(time.time())
    target_id = str(uuid.uuid4())
    with database.get_connection() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO tenants (id, name, created_at)
            VALUES (?, ?, ?)
            """,
            ("default", "Retrieval benchmark", now),
        )

        rows: list[
            tuple[str, str, float, float, int, float, int, int, int, str, int]
        ] = []
        for index in range(DATASET_SIZE):
            is_target = index == DATASET_SIZE // 2
            memory_id = target_id if is_target else str(uuid.uuid4())
            content = (
                TARGET_CONTENT
                if is_target
                else (
                    f"群聊闲谈编号 {index}：今天天气不错，"
                    "午饭吃了米饭，周末准备去公园散步。"
                )
            )
            rows.append(
                (
                    memory_id,
                    content,
                    1.0,
                    0.000000001,
                    0,
                    1.0,
                    now,
                    now,
                    now,
                    "active",
                    now,
                )
            )
            if len(rows) == BATCH_SIZE:
                connection.executemany(
                    """
                    INSERT INTO memories (
                        id, tenant_id, content, base_weight, decay_lambda,
                        retrieval_count, decayed_weight, last_decay_at, valid_from,
                        tx_time, status, created_at
                    )
                    VALUES (?, 'default', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                rows.clear()
        if rows:
            connection.executemany(
                """
                INSERT INTO memories (
                    id, tenant_id, content, base_weight, decay_lambda,
                    retrieval_count, decayed_weight, last_decay_at, valid_from,
                    tx_time, status, created_at
                )
                VALUES (?, 'default', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

        actual_count = int(
            connection.execute("SELECT count(*) FROM memories").fetchone()[0]
        )
    if actual_count != DATASET_SIZE:
        raise AssertionError(
            f"预期 {DATASET_SIZE} 条基准记忆，实际得到 {actual_count}"
        )
    return target_id


def benchmark() -> None:
    """Build the isolated corpus, warm the index, and report latency percentiles."""
    with tempfile.TemporaryDirectory(prefix="recallweaver-fts-bench-") as temp_dir:
        database = Database(str(Path(temp_dir) / "retrieval-benchmark.db"))
        database.init_db(verbose=False)
        target_id = _insert_benchmark_corpus(database)
        retriever = Retriever(database=database)

        initial_results = retriever.search(QUERY, limit=5)
        if not any(result["id"] == target_id for result in initial_results):
            raise AssertionError(
                "中文基准查询未能在 100,000 条数据中命中目标记忆"
            )

        latencies_ms: list[float] = []
        for _ in range(REPETITIONS):
            started_at = time.perf_counter()
            results = retriever.search(QUERY, limit=5)
            latencies_ms.append((time.perf_counter() - started_at) * 1_000)
            if not any(result["id"] == target_id for result in results):
                raise AssertionError("重复检索中丢失目标中文记忆")

        ordered_latencies = sorted(latencies_ms)
        p95 = ordered_latencies[(95 * len(ordered_latencies) + 99) // 100 - 1]
        print(f"数据量：{DATASET_SIZE:,} 条（隔离临时 SQLite 数据库）")
        print(f"查询：{QUERY}")
        print(f"每次结果：{len(initial_results)} 条，目标记忆精准命中")
        print(f"测量次数：{REPETITIONS} 次")
        print(f"平均延迟：{statistics.fmean(latencies_ms):.3f} ms")
        print(f"P95 延迟：{p95:.3f} ms")
        print(f"最大延迟：{max(latencies_ms):.3f} ms")
        print(f"10 ms 目标：{'通过' if p95 < 10.0 else '未通过'}")


if __name__ == "__main__":
    benchmark()
