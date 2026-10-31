"""Semantic and temporal benchmarks for RecallWeaver's real-world behaviors.

Run ``python benchmarks/bench_real_world.py`` to run the reproducible local
suite. Use ``--download-huggingface`` to opt in to public dataset downloads;
network failures automatically select schema-compatible local mock datasets.
All persistent dataset files are stored under ``benchmarks/datasets`` and all
database-backed scenarios use a pytest-managed shared in-memory SQLite DB.
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import sys
import time
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = PROJECT_ROOT / "benchmarks"
DATASET_DIR = BENCHMARK_DIR / "datasets"
SOURCE_DIR = PROJECT_ROOT / "src"
for import_path in (str(PROJECT_ROOT), str(BENCHMARK_DIR), str(SOURCE_DIR)):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

from dataset_loaders import (
    DatasetDownloadError,
    DatasetLoadError,
    FactConflictLoader,
    FactConflictRecord,
    LongMemEvalLoader,
    LongMemEvalSample,
    download_huggingface_dataset,
    generate_daily_chatter_corpus,
    generate_mock_fact_conflicts,
    generate_mock_longmemeval_record,
    write_json_dataset,
)
from recallweaver.api import RecallWeaverAPI
from recallweaver.db import Database
from recallweaver.decay_engine import DecayEngine
from recallweaver.graph import GraphManager
from recallweaver.memory_manager import MemoryManager
from recallweaver.retrieval import Retriever

LONGMEMEVAL_FILE = DATASET_DIR / "longmemeval_mock.json"
FACT_CONFLICT_FILE = DATASET_DIR / "fact_conflicts_mock.json"
LONGMEMEVAL_OFFICIAL_FILE = DATASET_DIR / "longmemeval_s_cleaned.json"
FACT_CONFLICT_OFFICIAL_FILE = DATASET_DIR / "FactConsolidation.json"
DAILY_CHATTER_FILE = DATASET_DIR / "daily_chatter.json"
LONGMEMEVAL_DATASET_PATH = LONGMEMEVAL_FILE
FACT_CONFLICT_DATASET_PATH = FACT_CONFLICT_FILE
P95_BUDGET_MS = 10.0
LONGMEMEVAL_DATASET_ID = "xiaowu0162/longmemeval-cleaned"
LONGMEMEVAL_FILENAME = "longmemeval_s_cleaned.json"
FACT_DATASET_ID = "meme-benchmark/MEME"
FACT_FILENAME = "FactConsolidation.json"


class InMemoryDatabase(Database):
    """Provide one shared in-memory connection with production transaction semantics."""

    def __init__(self) -> None:
        """Create a schema-initialized isolated SQLite memory database."""
        super().__init__(":memory:")
        self._connection = sqlite3.connect(":memory:")
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        schema_path = PROJECT_ROOT / "schema.sql"
        try:
            schema_sql = schema_path.read_text(encoding="utf-8")
            self._connection.executescript(schema_sql)
        except (OSError, sqlite3.Error) as exc:
            self._connection.close()
            raise RuntimeError(f"无法初始化基准内存数据库：{exc}") from exc

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Yield the shared connection and commit or roll back each operation.

        Yields:
            The shared row-mapped SQLite connection.

        Raises:
            sqlite3.Error: Database errors propagate to the RecallWeaver API
                boundary, which translates them to project-specific errors.
        """
        try:
            yield self._connection
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise

    def close(self) -> None:
        """Close the shared connection and release its in-memory database."""
        try:
            self._connection.close()
        except sqlite3.Error as exc:
            raise RuntimeError(f"关闭基准内存数据库失败：{exc}") from exc


def create_in_memory_api(database: InMemoryDatabase) -> RecallWeaverAPI:
    """Assemble the public API over an already initialized in-memory database.

    Args:
        database: Shared in-memory SQLite database for one scenario.

    Returns:
        RecallWeaver API whose managers all share the supplied database.
    """
    api = RecallWeaverAPI.__new__(RecallWeaverAPI)
    api.database_manager = database
    api.decay_engine = DecayEngine()
    api.memory_manager = MemoryManager(database=database)
    api.graph_manager = GraphManager(database=database)
    api.retriever = Retriever(
        database=database,
        decay_engine=api.decay_engine,
    )
    return api


@pytest.fixture
def isolated_api() -> Iterator[RecallWeaverAPI]:
    """Create an isolated in-memory API for one benchmark test.

    Yields:
        Public API with a fresh schema and no files shared with the user DB.
    """
    database = InMemoryDatabase()
    try:
        yield create_in_memory_api(database)
    finally:
        database.close()


def ensure_local_datasets(*, download_official: bool = False) -> None:
    """Ensure benchmark source files exist, falling back to realistic local data.

    Args:
        download_official: If true, attempt official Hugging Face downloads
            before generating local fallback datasets.

    Raises:
        RuntimeError: If fallback data cannot be persisted under datasets.
    """
    global FACT_CONFLICT_DATASET_PATH, LONGMEMEVAL_DATASET_PATH
    LONGMEMEVAL_DATASET_PATH = LONGMEMEVAL_FILE
    FACT_CONFLICT_DATASET_PATH = FACT_CONFLICT_FILE
    try:
        DATASET_DIR.mkdir(parents=True, exist_ok=True)
        if download_official:
            try:
                download_huggingface_dataset(
                    LONGMEMEVAL_DATASET_ID,
                    LONGMEMEVAL_FILENAME,
                    LONGMEMEVAL_OFFICIAL_FILE,
                    timeout=5.0,
                    retries=1,
                )
                official_samples = LongMemEvalLoader().load(
                    str(LONGMEMEVAL_OFFICIAL_FILE)
                )
                if not any(
                    len(messages) >= 50
                    and sum(
                        len(message["content"].split())
                        for message in messages
                    )
                    >= 190_000
                    for messages, _, _ in official_samples
                ):
                    raise ValueError(
                        "没有满足 50 条消息和约 200k token 的样本"
                    )
                LONGMEMEVAL_DATASET_PATH = LONGMEMEVAL_OFFICIAL_FILE
            except (DatasetDownloadError, ValueError) as exc:
                print(
                    "LongMemEval 官方源不可用或格式不兼容，"
                    f"使用本地 Mock Fallback：{exc}"
                )
            try:
                download_huggingface_dataset(
                    FACT_DATASET_ID,
                    FACT_FILENAME,
                    FACT_CONFLICT_OFFICIAL_FILE,
                    timeout=5.0,
                    retries=1,
                )
                official_conflicts = FactConflictLoader().load(
                    str(FACT_CONFLICT_OFFICIAL_FILE)
                )
                _select_conflict_chain(official_conflicts)
                FACT_CONFLICT_DATASET_PATH = FACT_CONFLICT_OFFICIAL_FILE
            except (DatasetDownloadError, ValueError) as exc:
                print(
                    "FactConsolidation 官方源不可用或缺少连续演变链，"
                    f"使用本地 Mock Fallback：{exc}"
                )

        longmemeval_is_usable = False
        if LONGMEMEVAL_FILE.exists():
            try:
                local_samples = LongMemEvalLoader().load(str(LONGMEMEVAL_FILE))
                longmemeval_is_usable = any(
                    len(messages) >= 50
                    and sum(
                        len(message["content"].split())
                        for message in messages
                    )
                    >= 190_000
                    for messages, _, _ in local_samples
                )
            except ValueError:
                longmemeval_is_usable = False
        if not longmemeval_is_usable:
            write_json_dataset(
                LONGMEMEVAL_FILE,
                [generate_mock_longmemeval_record(turns=60, token_budget=200_000)],
            )

        conflict_chain_is_usable = False
        if FACT_CONFLICT_FILE.exists():
            try:
                _select_conflict_chain(
                    FactConflictLoader().load(str(FACT_CONFLICT_FILE))
                )
                conflict_chain_is_usable = True
            except ValueError:
                conflict_chain_is_usable = False
        if not conflict_chain_is_usable:
            write_json_dataset(
                FACT_CONFLICT_FILE,
                generate_mock_fact_conflicts(count=4),
            )
        if not DAILY_CHATTER_FILE.exists():
            write_json_dataset(DAILY_CHATTER_FILE, generate_daily_chatter_corpus())
    except (OSError, DatasetLoadError, ValueError, TypeError) as exc:
        raise RuntimeError(f"准备本地基准数据失败：{exc}") from exc


@pytest.fixture(scope="module", autouse=True)
def benchmark_dataset_files() -> Iterator[None]:
    """Make local fallback corpora available for direct pytest invocations."""
    ensure_local_datasets()
    yield


def _load_longmemeval_sample() -> LongMemEvalSample:
    """Load the selected LongMemEval sample or report an invalid export.

    Returns:
        The first canonical conversation, target question and answer.
    """
    samples = LongMemEvalLoader().load(str(LONGMEMEVAL_DATASET_PATH))
    eligible_samples = [
        sample
        for sample in samples
        if len(sample[0]) >= 50
        and sum(len(message["content"].split()) for message in sample[0])
        >= 190_000
    ]
    if not eligible_samples:
        raise ValueError("没有满足 50 条消息和约 200k token 的 LongMemEval 样本")
    return max(
        eligible_samples,
        key=lambda sample: sum(
            len(message["content"].split()) for message in sample[0]
        ),
    )


def _load_conflict_records() -> list[FactConflictRecord]:
    """Load the selected fact-conflict dataset.

    Returns:
        Validated chronological fact-conflict records.
    """
    return FactConflictLoader().load(str(FACT_CONFLICT_DATASET_PATH))


def _select_conflict_chain(
    records: list[FactConflictRecord],
) -> list[FactConflictRecord]:
    """Select the longest chronological old-to-new chain from a dataset.

    Args:
        records: Validated transitions from one or more subjects/relations.

    Returns:
        The longest chain in which each transition's new value equals the next
        transition's old value.

    Raises:
        ValueError: If no connected chain contains at least two transitions.
    """
    grouped: dict[tuple[str, str], list[FactConflictRecord]] = {}
    for record in records:
        grouped.setdefault((record.subject, record.predicate), []).append(record)

    longest_chain: list[FactConflictRecord] = []
    for group in grouped.values():
        ordered = sorted(
            group,
            key=lambda record: _parse_utc_timestamp(record.timestamp),
        )
        for start_index, first_record in enumerate(ordered):
            chain = [first_record]
            for candidate in ordered[start_index + 1 :]:
                if (
                    candidate.old_object == chain[-1].new_object
                    and _parse_utc_timestamp(candidate.timestamp)
                    > _parse_utc_timestamp(chain[-1].timestamp)
                ):
                    chain.append(candidate)
            if len(chain) > len(longest_chain):
                longest_chain = chain

    if len(longest_chain) < 2:
        raise ValueError("事实数据集中没有至少两步连续且时间递增的冲突链")
    return longest_chain


def _write_timed_fact(
    api: RecallWeaverAPI,
    *,
    subject: str,
    predicate: str,
    object_: str,
    valid_from: str,
) -> None:
    """Write a fact version and apply its source business-effective timestamp.

    The public write API currently timestamps changes at ingestion time. This
    benchmark explicitly backdates business-valid time from the dataset while
    preserving the production conflict-resolution transaction.

    Args:
        api: API backed by the isolated in-memory SQLite database.
        subject: Entity owning the fact.
        predicate: Fact relationship.
        object_: Fact value.
        valid_from: UTC ISO-8601 business-effective timestamp from the dataset.
    """
    api.remember_triple(subject, predicate, object_)
    with api.database_manager.get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE edges
            SET valid_from = ?
            WHERE tenant_id = ?
              AND predicate = ?
              AND valid_to IS NULL
              AND subject_id = (
                  SELECT id FROM entities
                  WHERE tenant_id = ? AND name = ?
              )
              AND object_id = (
                  SELECT id FROM entities
                  WHERE tenant_id = ? AND name = ?
              )
            """,
            (
                valid_from,
                "default",
                predicate,
                "default",
                subject,
                "default",
                object_,
            ),
        )
    if cursor.rowcount != 1:
        raise AssertionError(
            f"预期只更新一条新事实边，实际更新 {cursor.rowcount} 条"
        )


def _set_predecessor_end_time(
    api: RecallWeaverAPI,
    *,
    subject: str,
    predicate: str,
    object_: str,
    valid_to: str,
) -> None:
    """Set a prior fact's end to the next version's dataset start.

    Args:
        api: API backed by the isolated in-memory SQLite database.
        subject: Entity owning the fact.
        predicate: Fact relationship.
        object_: Previous fact value.
        valid_to: UTC timestamp at which the previous value ceased to apply.
    """
    with api.database_manager.get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE edges
            SET valid_to = ?
            WHERE tenant_id = ?
              AND predicate = ?
              AND valid_to IS NOT NULL
              AND subject_id = (
                  SELECT id FROM entities
                  WHERE tenant_id = ? AND name = ?
              )
              AND object_id = (
                  SELECT id FROM entities
                  WHERE tenant_id = ? AND name = ?
              )
            """,
            (
                valid_to,
                "default",
                predicate,
                "default",
                subject,
                "default",
                object_,
            ),
        )
    if cursor.rowcount != 1:
        raise AssertionError(
            f"预期只关闭一条旧事实边，实际更新 {cursor.rowcount} 条"
        )


def _parse_utc_timestamp(value: str) -> datetime:
    """Parse an ISO timestamp into an aware UTC datetime.

    Args:
        value: ISO-8601 timestamp from a fact-history result.

    Returns:
        Parsed timezone-aware datetime.

    Raises:
        ValueError: If a stored timestamp is malformed or lacks timezone data.
    """
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"时间戳必须包含时区：{value}")
    return parsed


def _p95(values_ms: list[float]) -> float:
    """Compute nearest-rank 95th percentile without third-party dependencies.

    Args:
        values_ms: Non-empty measurement list in milliseconds.

    Returns:
        Nearest-rank P95 latency.

    Raises:
        ValueError: If no latency observations were collected.
    """
    if not values_ms:
        raise ValueError("P95 计算至少需要一个测量值")
    ordered = sorted(values_ms)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def test_longmemeval_needle_recall_and_latency(
    isolated_api: RecallWeaverAPI,
) -> None:
    """Find a needle answer in a roughly 200k-token long-memory history."""
    history_messages, question, ground_truth = _load_longmemeval_sample()
    assert len(history_messages) >= 50, "长程基准必须至少包含 50 条历史消息"
    estimated_tokens = sum(
        len(message["content"].split()) for message in history_messages
    )
    assert estimated_tokens >= 190_000, (
        f"长上下文预算不足：estimated_tokens={estimated_tokens}"
    )

    for message_index, message in enumerate(history_messages):
        isolated_api.add_memory(
            f"[longmemeval message {message_index} {message['role']}] "
            f"{message['content']}"
        )

    latencies_ms: list[float] = []
    results = []
    for _ in range(25):
        started = time.perf_counter()
        results = isolated_api.recall(question, limit=3)
        latencies_ms.append((time.perf_counter() - started) * 1000)

    assert any(
        result.content is not None and ground_truth.casefold() in result.content.casefold()
        for result in results
    ), f"Top-3 未包含 ground_truth={ground_truth!r}"
    p95_ms = _p95(latencies_ms)
    assert p95_ms < P95_BUDGET_MS, (
        f"LongMemEval P95={p95_ms:.3f} ms 超过 {P95_BUDGET_MS:.1f} ms"
    )
    print(
        f"LongMemEval: {len(history_messages)} messages, "
        f"~{estimated_tokens} whitespace tokens, P95={p95_ms:.3f} ms"
    )


def test_when_facts_expire_timeline_is_contiguous(
    isolated_api: RecallWeaverAPI,
) -> None:
    """Apply successive CEO changes and prove all validity intervals close."""
    records = _select_conflict_chain(_load_conflict_records())
    subject = records[0].subject
    predicate = records[0].predicate
    assert all(
        record.subject == subject and record.predicate == predicate
        for record in records
    ), "时序演变记录必须属于同一主语和谓词"
    assert len(records) >= 2

    first_effective_time = _parse_utc_timestamp(records[0].timestamp) - timedelta(
        microseconds=1
    )
    first_timestamp = first_effective_time.isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
    first_old_object = records[0].old_object
    _write_timed_fact(
        isolated_api,
        subject=subject,
        predicate=predicate,
        object_=first_old_object,
        valid_from=first_timestamp,
    )

    expected_objects = [first_old_object]
    previous_object = first_old_object
    for record in records:
        assert record.old_object == previous_object, (
            "事实演变记录必须首尾相接："
            f"预期旧值 {previous_object!r}，实际 {record.old_object!r}"
        )
        _write_timed_fact(
            isolated_api,
            subject=subject,
            predicate=predicate,
            object_=record.new_object,
            valid_from=record.timestamp,
        )
        _set_predecessor_end_time(
            isolated_api,
            subject=subject,
            predicate=predicate,
            object_=record.old_object,
            valid_to=record.timestamp,
        )
        expected_objects.append(record.new_object)
        previous_object = record.new_object

    history = isolated_api.get_history(subject, predicate)
    assert [item["object"] for item in history] == expected_objects
    assert len(history) == len(expected_objects)
    for index, item in enumerate(history):
        valid_from = _parse_utc_timestamp(str(item["valid_from"]))
        if index < len(history) - 1:
            valid_to = _parse_utc_timestamp(str(item["valid_to"]))
            next_valid_from = _parse_utc_timestamp(
                str(history[index + 1]["valid_from"])
            )
            assert valid_to == next_valid_from, (
                f"时间线第 {index} 段存在断裂或重叠："
                f"{valid_to.isoformat()} != {next_valid_from.isoformat()}"
            )
            assert valid_to > valid_from
        else:
            assert item["valid_to"] is None

    with isolated_api.database_manager.get_connection() as connection:
        raw_edges = connection.execute(
            """
            SELECT edge.valid_from, edge.valid_to, object.name AS object_name
            FROM edges AS edge
            JOIN entities AS subject
              ON subject.id = edge.subject_id
             AND subject.tenant_id = edge.tenant_id
            JOIN entities AS object
              ON object.id = edge.object_id
             AND object.tenant_id = edge.tenant_id
            WHERE edge.tenant_id = ? AND subject.name = ? AND edge.predicate = ?
            ORDER BY edge.valid_from
            """,
            ("default", subject, predicate),
        ).fetchall()
    assert len(raw_edges) == len(expected_objects)
    assert sum(row["valid_to"] is None for row in raw_edges) == 1
    assert all(row["valid_from"] for row in raw_edges)


def test_dolphinbench_daily_noise_does_not_displace_core_fact(
    isolated_api: RecallWeaverAPI,
) -> None:
    """A high-weight allergy fact survives 500 chatter records on each side."""
    try:
        chatter_lines = json.loads(DAILY_CHATTER_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AssertionError(f"无法读取日常聊天语料：{exc}") from exc
    assert isinstance(chatter_lines, list) and chatter_lines

    for index in range(500):
        chatter = str(chatter_lines[index % len(chatter_lines)])
        isolated_api.memory_manager.remember(
            f"日常生活闲聊记录：{chatter} 噪音编号{index}",
            base_weight=0.05,
        )

    core_memory_id = isolated_api.memory_manager.remember(
        "日常生活关联的核心健康事实：用户对青霉素过敏。",
        base_weight=2.0,
    )

    for index in range(500, 1000):
        chatter = str(chatter_lines[index % len(chatter_lines)])
        isolated_api.memory_manager.remember(
            f"日常生活闲聊记录：{chatter} 噪音编号{index}",
            base_weight=0.05,
        )

    results = isolated_api.recall("日常生活", limit=3)
    assert results and results[0].memory_id == core_memory_id
    assert results[0].content is not None
    assert "青霉素过敏" in results[0].content
    assert all(result.score >= isolated_api.retriever.SCORE_THRESHOLD for result in results)

    with isolated_api.database_manager.get_connection() as connection:
        counts = connection.execute(
            """
            SELECT
                count(*) AS total,
                sum(CASE WHEN content LIKE '%噪音编号%' THEN 1 ELSE 0 END) AS noise,
                sum(CASE WHEN id = ? AND base_weight = 2.0 THEN 1 ELSE 0 END) AS core
            FROM memories
            """,
            (core_memory_id,),
        ).fetchone()
    assert counts["total"] == 1001
    assert counts["noise"] == 1000
    assert counts["core"] == 1


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse standalone benchmark command-line options.

    Args:
        argv: Optional explicit argument list for tests or embedding callers.

    Returns:
        Parsed command-line namespace.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--download-huggingface",
        action="store_true",
        help="Try official public datasets; use generated fallback on failure",
    )
    parser.add_argument(
        "--longmemeval-path",
        type=Path,
        help="Use an already-downloaded LongMemEval JSON file",
    )
    parser.add_argument(
        "--fact-conflict-path",
        type=Path,
        help="Use an already-downloaded FactConsolidation JSON file",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Prepare benchmark datasets and run the pytest scenarios.

    Args:
        argv: Optional command-line argument list.

    Returns:
        Pytest process status code.
    """
    global FACT_CONFLICT_DATASET_PATH, LONGMEMEVAL_DATASET_PATH
    args = _parse_args(argv)
    try:
        ensure_local_datasets(download_official=args.download_huggingface)
    except RuntimeError as exc:
        print(f"准备 benchmark 数据失败：{exc}", file=sys.stderr)
        return 1
    if args.longmemeval_path is not None:
        LONGMEMEVAL_DATASET_PATH = args.longmemeval_path
    if args.fact_conflict_path is not None:
        FACT_CONFLICT_DATASET_PATH = args.fact_conflict_path
    return int(pytest.main([str(Path(__file__).resolve()), "-q", "-s"]))


if __name__ == "__main__":
    raise SystemExit(main())
