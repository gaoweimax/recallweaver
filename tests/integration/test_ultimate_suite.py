"""File-backed stress tests for temporal facts, FTS, and retrieval ranking."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from benchmarks.gen_complex_data import TOTAL_RECORDS, write_jsonl
from recallweaver.api import RecallWeaverAPI


@dataclass
class UltimateSuiteMetrics:
    """Measurements emitted after the complete ultimate test module."""

    started_at: float = field(default_factory=time.perf_counter)
    persisted_records: int = 0
    dataset_records: int = 0
    retrieval_latencies_ms: list[float] = field(default_factory=list)
    conflict_scenarios_attempted: int = 0
    conflict_scenarios_passed: int = 0


@pytest.fixture
def ultimate_api(tmp_path: Path) -> Iterator[RecallWeaverAPI]:
    """Create a dedicated temporary file-backed database for one scenario.

    Args:
        tmp_path: Pytest's per-test temporary directory.

    Yields:
        An API instance initialized against a database isolated to this test.
    """
    api = RecallWeaverAPI(str(tmp_path / "ultimate-suite.sqlite3"))
    yield api


@pytest.fixture(scope="module")
def ultimate_metrics(
    pytestconfig: pytest.Config,
) -> Iterator[UltimateSuiteMetrics]:
    """Collect module measurements and print a Markdown summary at teardown.

    Args:
        pytestconfig: Active pytest configuration and terminal reporter.

    Yields:
        Mutable measurements shared only by this test module.
    """
    metrics = UltimateSuiteMetrics()
    yield metrics

    elapsed_seconds = time.perf_counter() - metrics.started_at
    if metrics.retrieval_latencies_ms:
        ordered_latencies = sorted(metrics.retrieval_latencies_ms)
        p95_index = math.ceil(0.95 * len(ordered_latencies)) - 1
        p95_ms = ordered_latencies[p95_index]
        p95_text = f"{p95_ms:.3f} ms"
    else:
        p95_text = "N/A"

    if metrics.conflict_scenarios_attempted:
        conflict_rate = (
            metrics.conflict_scenarios_passed
            / metrics.conflict_scenarios_attempted
            * 100
        )
        conflict_text = (
            f"{conflict_rate:.1f}% "
            f"({metrics.conflict_scenarios_passed}/"
            f"{metrics.conflict_scenarios_attempted})"
        )
    else:
        conflict_text = "N/A"

    report_lines = [
        "| 指标 | 结果 |",
        "|---|---:|",
        f"| 压测数据集记录数 | {metrics.dataset_records:,} |",
        f"| 场景数据库持久化记录数 | {metrics.persisted_records:,} |",
        f"| 测试总耗时 | {elapsed_seconds:.3f} 秒 |",
        f"| 海量数据检索 P95 | {p95_text} |",
        f"| 事实冲突场景通过率 | {conflict_text} |",
    ]
    terminal_reporter = pytestconfig.pluginmanager.get_plugin(
        "terminalreporter"
    )
    if terminal_reporter is not None:
        terminal_reporter.write_sep("=", "Ultimate ACID and retrieval report")
        for line in report_lines:
            terminal_reporter.write_line(line)


def test_rapid_concurrent_residence_conflicts_are_contiguous(
    ultimate_api: RecallWeaverAPI,
    ultimate_metrics: UltimateSuiteMetrics,
) -> None:
    """Concurrent updates leave a single current edge and closed intervals."""
    ultimate_metrics.conflict_scenarios_attempted += 1
    changes = ("北京", "上海", "广州")
    concurrent_updates = [
        ("user_1", city) for city in changes
    ] + [
        ("user_2", city) for city in ("成都", "杭州", "深圳")
    ]
    started_at = time.perf_counter()

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(
                ultimate_api.remember_triple,
                subject,
                "居住地",
                city,
            )
            for subject, city in concurrent_updates
        ]
        assert all(future.result() is True for future in futures)

    elapsed_seconds = time.perf_counter() - started_at
    assert elapsed_seconds < 1.0

    with ultimate_api.database_manager.get_connection() as connection:
        rows = connection.execute(
            """
            SELECT edge.valid_from, edge.valid_to, object.name AS city
            FROM edges AS edge
            JOIN entities AS subject
              ON subject.id = edge.subject_id
             AND subject.tenant_id = edge.tenant_id
            JOIN entities AS object
              ON object.id = edge.object_id
             AND object.tenant_id = edge.tenant_id
            WHERE edge.tenant_id = ? AND subject.name = ? AND edge.predicate = ?
            ORDER BY edge.valid_from, edge.id
            """,
            ("default", "user_1", "居住地"),
        ).fetchall()
        second_user_rows = connection.execute(
            """
            SELECT edge.valid_from, edge.valid_to, object.name AS city
            FROM edges AS edge
            JOIN entities AS subject
              ON subject.id = edge.subject_id
             AND subject.tenant_id = edge.tenant_id
            JOIN entities AS object
              ON object.id = edge.object_id
             AND object.tenant_id = edge.tenant_id
            WHERE edge.tenant_id = ? AND subject.name = ? AND edge.predicate = ?
            """,
            ("default", "user_2", "居住地"),
        ).fetchall()
        edge_count = connection.execute(
            "SELECT count(*) FROM edges"
        ).fetchone()[0]

    assert len(rows) == 3
    assert {row["city"] for row in rows} == set(changes)
    assert sum(row["valid_to"] is None for row in rows) == 1
    for current, following in zip(rows, rows[1:]):
        assert current["valid_to"] is not None
        assert current["valid_to"] == following["valid_from"]
        assert current["valid_from"] < following["valid_from"]
    assert rows[-1]["valid_to"] is None
    assert len(second_user_rows) == 3
    assert sum(row["valid_to"] is None for row in second_user_rows) == 1
    assert edge_count == 6

    ultimate_metrics.persisted_records += edge_count
    ultimate_metrics.conflict_scenarios_passed += 1


def test_fifty_thousand_memories_recall_the_unique_allergy_fact(
    tmp_path: Path,
    ultimate_api: RecallWeaverAPI,
    ultimate_metrics: UltimateSuiteMetrics,
) -> None:
    """Import the generated corpus and find user 88's fact within 10 ms P95."""
    dataset_path = tmp_path / "complex-data.jsonl"
    assert write_jsonl(dataset_path) == TOTAL_RECORDS

    def iter_records() -> Iterator[dict[str, object]]:
        """Decode JSONL rows lazily so bulk import stays memory-bounded."""
        with dataset_path.open("r", encoding="utf-8") as dataset_file:
            for line in dataset_file:
                record = json.loads(line)
                assert isinstance(record, dict)
                yield record

    record_count = 0
    noise_count = 0
    move_count = 0
    fact_count = 0
    now = int(time.time())
    with ultimate_api.database_manager.get_connection() as connection:
        connection.executemany(
            """
            INSERT OR IGNORE INTO tenants (id, name, created_at)
            VALUES (?, ?, ?)
            """,
            (
                (f"user_{user_number}", f"user_{user_number}", now)
                for user_number in range(1, 501)
            ),
        )
        connection.execute(
            """
            INSERT INTO tenants (id, name, created_at)
            VALUES (?, ?, ?)
            """,
            ("group-chat", "group-chat", now),
        )
        connection.executemany(
            """
            INSERT INTO memories (
                id, tenant_id, content, memory_type, instruction_weight,
                emotion_weight, base_weight, decay_lambda, retrieval_count,
                last_decay_at, decayed_weight, valid_from, valid_to, tx_time,
                status, created_at
            )
            VALUES (?, ?, ?, 'fact', 1.0, 1.0, ?, 0.01, 0, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    record["memory_id"],
                    record["tenant_id"],
                    record["content"],
                    record["base_weight"],
                    record["created_at"],
                    record["base_weight"],
                    record["valid_from"],
                    record["valid_to"],
                    record["created_at"],
                    record["status"],
                    record["created_at"],
                )
                for record in iter_records()
            ),
        )
        with dataset_path.open("r", encoding="utf-8") as dataset_file:
            for line in dataset_file:
                record = json.loads(line)
                assert isinstance(record, dict)
                record_count += 1
                noise_count += record["kind"] == "noise"
                move_count += record["kind"] == "residence_change"
                fact_count += record["kind"] == "fact"
        imported_count = connection.execute(
            "SELECT count(*) FROM memories"
        ).fetchone()[0]
        tenant_count = connection.execute(
            "SELECT count(*) FROM tenants"
        ).fetchone()[0]
        tenant_memory_counts = connection.execute(
            """
            SELECT tenant_id, count(*) AS memory_count
            FROM memories
            GROUP BY tenant_id
            """
        ).fetchall()

    assert imported_count == TOTAL_RECORDS
    assert record_count == TOTAL_RECORDS
    assert noise_count == 46_500
    assert move_count == 1_500
    assert fact_count == 2_000
    assert tenant_count == 501
    assert len(tenant_memory_counts) == 501
    assert all(
        row["memory_count"] == 7
        for row in tenant_memory_counts
        if row["tenant_id"].startswith("user_")
    )
    assert next(
        row["memory_count"]
        for row in tenant_memory_counts
        if row["tenant_id"] == "group-chat"
    ) == 46_500
    ultimate_metrics.dataset_records = imported_count
    ultimate_metrics.persisted_records += imported_count

    query = "user_88 对什么过敏？"
    expected_content = "user_88 对花生过敏。"
    results = ultimate_api.recall(
        query,
        limit=3,
        tenant_id="user_88",
    )
    assert len(results) == 1
    assert results[0].content == expected_content

    noise_score = ultimate_api.decay_engine.calculate_score(
        base_weight=0.1,
        decay_lambda=0.01,
        last_decay_at=int(time.time()),
        retrieval_count=0,
    )
    assert results[0].score >= noise_score * 10

    for _ in range(30):
        query_started_at = time.perf_counter()
        repeated_results = ultimate_api.recall(
            query,
            limit=3,
            tenant_id="user_88",
        )
        ultimate_metrics.retrieval_latencies_ms.append(
            (time.perf_counter() - query_started_at) * 1_000
        )
        assert len(repeated_results) == 1
        assert repeated_results[0].content == expected_content

    ordered_latencies = sorted(ultimate_metrics.retrieval_latencies_ms)
    p95_index = math.ceil(0.95 * len(ordered_latencies)) - 1
    assert ordered_latencies[p95_index] < 10.0


def test_recursive_graph_traversal_stops_at_depth_on_a_cycle(
    ultimate_api: RecallWeaverAPI,
    ultimate_metrics: UltimateSuiteMetrics,
) -> None:
    """A twelve-edge cycle is bounded by the requested recursive CTE depth."""
    nodes = tuple(f"node_{index}" for index in range(12))
    for index, subject in enumerate(nodes):
        object_ = nodes[(index + 1) % len(nodes)]
        ultimate_api.graph_manager.add_edge(
            subject,
            "认识",
            object_,
        )

    max_depth = 6
    paths = ultimate_api.graph_manager.query_multi_hop(
        nodes[0],
        depth=max_depth,
    )

    assert len(paths) == max_depth
    assert max(path["depth"] for path in paths) == max_depth
    assert all(1 <= path["depth"] <= max_depth for path in paths)
    assert len({path["entity_id"] for path in paths}) == max_depth

    with ultimate_api.database_manager.get_connection() as connection:
        edge_count = connection.execute(
            "SELECT count(*) FROM edges"
        ).fetchone()[0]
    assert edge_count == len(nodes)
    ultimate_metrics.persisted_records += edge_count


def test_pathological_fts_text_does_not_break_normal_chinese_search(
    ultimate_api: RecallWeaverAPI,
    ultimate_metrics: UltimateSuiteMetrics,
) -> None:
    """Special characters, rare ideographs, and a long token remain safe."""
    pathological_text = (
        "A" * 600_000
        + "Ω☣龘靐齉<>!@#$%^&*()[]{};:，。！？" * 35_000
    )
    assert len(pathological_text) > 500_000
    ultimate_api.add_memory(pathological_text)
    target_id = ultimate_api.add_memory(
        "青霉素过敏，是需要长期保留的核心事实。"
    )

    results = ultimate_api.recall("青霉素过敏", limit=5)
    assert results
    assert results[0].memory_id == target_id
    assert results[0].content == "青霉素过敏，是需要长期保留的核心事实。"

    with ultimate_api.database_manager.get_connection() as connection:
        fts_table = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = ? AND name = ?
            """,
            ("table", "memories_fts"),
        ).fetchone()
        stored_length = connection.execute(
            "SELECT length(content) FROM memories WHERE id = ?",
            (results[0].memory_id,),
        ).fetchone()[0]
        memory_count = connection.execute(
            "SELECT count(*) FROM memories"
        ).fetchone()[0]

    assert fts_table is not None
    assert stored_length == len("青霉素过敏，是需要长期保留的核心事实。")
    assert memory_count == 2
    ultimate_metrics.persisted_records += memory_count


def test_capped_retrieval_boost_cannot_resurrect_stale_memory(
    ultimate_api: RecallWeaverAPI,
    ultimate_metrics: UltimateSuiteMetrics,
) -> None:
    """A one-year-old, heavily retrieved fact ranks below a fresh version."""
    old_id = ultimate_api.add_memory(
        "user_drink_preference coffee",
    )
    new_id = ultimate_api.add_memory(
        "user_drink_preference tea",
    )
    now = int(time.time())
    one_year_ago = now - 365 * 24 * 60 * 60

    with ultimate_api.database_manager.get_connection() as connection:
        connection.execute(
            """
            UPDATE memories
            SET base_weight = ?, decay_lambda = ?, last_decay_at = ?,
                retrieval_count = ?
            WHERE id = ?
            """,
            (0.8, 0.00000001, one_year_ago, 1_000, old_id),
        )
        connection.execute(
            """
            UPDATE memories
            SET base_weight = ?, decay_lambda = ?, last_decay_at = ?,
                retrieval_count = ?
            WHERE id = ?
            """,
            (1.0, 0.00000001, now, 0, new_id),
        )

    results = ultimate_api.recall(
        "user_drink_preference",
        limit=5,
    )
    result_ids = [result.memory_id for result in results]
    assert result_ids == [new_id, old_id]
    assert results[0].score > results[1].score

    with ultimate_api.database_manager.get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, base_weight, retrieval_count, last_decay_at
            FROM memories
            WHERE id IN (?, ?)
            """,
            (old_id, new_id),
        ).fetchall()
    assert len(rows) == 2
    stored_old = next(row for row in rows if row["id"] == old_id)
    stored_new = next(row for row in rows if row["id"] == new_id)
    assert stored_old["retrieval_count"] == 1_000
    assert stored_old["base_weight"] == pytest.approx(0.8)
    assert stored_old["last_decay_at"] == one_year_ago
    assert stored_new["retrieval_count"] == 0
    assert stored_new["base_weight"] == pytest.approx(1.0)
    assert results[1].score == pytest.approx(
        0.8 * math.exp(-0.00000001 * (now - one_year_ago)) * 1.5,
        rel=0.05,
    )
    ultimate_metrics.persisted_records += len(rows)
