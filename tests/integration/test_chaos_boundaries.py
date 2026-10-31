"""Destructive boundary tests for memory retrieval and graph persistence."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from recallweaver.api import RecallWeaverAPI


@pytest.fixture
def chaos_api(tmp_path: Path) -> Iterator[RecallWeaverAPI]:
    """Create an isolated file-backed API instance for each chaos scenario.

    Args:
        tmp_path: Pytest-managed unique directory for this test invocation.

    Yields:
        A RecallWeaver API whose database is isolated from the project database.
    """
    api = RecallWeaverAPI(str(tmp_path / "chaos-boundaries.db"))
    yield api


def test_noise_flood_does_not_evict_core_fact(chaos_api: RecallWeaverAPI) -> None:
    """One important fact remains first after a flood of matching chatter."""
    for index in range(100):
        chaos_api.memory_manager.remember(
            f"张三今天花生哈哈天气不错噪音{index}",
            base_weight=0.1,
        )
    core_memory_id = chaos_api.memory_manager.remember(
        "张三对花生过敏",
        base_weight=1.0,
    )

    results = chaos_api.recall("张三", limit=10)

    assert results
    assert results[0].memory_id == core_memory_id
    assert results[0].content == "张三对花生过敏"
    assert all(
        result.score >= chaos_api.retriever.SCORE_THRESHOLD
        for result in results
    )
    assert all("噪音" not in (result.content or "") for result in results)

    # 直接核验原始写入数和每条噪音的低权重，没有依赖 API 返回值替代存储证据。
    with chaos_api.database_manager.get_connection() as connection:
        memory_rows = connection.execute(
            """
            SELECT content, base_weight, status
            FROM memories
            WHERE tenant_id = ?
            ORDER BY created_at, id
            """,
            ("default",),
        ).fetchall()
    noise_rows = [
        row for row in memory_rows if row["content"].startswith("张三今天")
    ]
    core_rows = [
        row for row in memory_rows if row["content"] == "张三对花生过敏"
    ]
    assert len(memory_rows) == 101
    assert len(noise_rows) == 100
    assert all(
        row["base_weight"] == pytest.approx(0.1)
        and row["status"] == "active"
        for row in noise_rows
    )
    assert len(core_rows) == 1
    assert core_rows[0]["base_weight"] == pytest.approx(1.0)
    assert core_rows[0]["status"] == "active"


def test_retrieval_count_manipulation_cannot_beat_conflicting_fact(
    chaos_api: RecallWeaverAPI,
) -> None:
    """An old low-weight milk fact cannot outrank its corrected replacement."""
    old_memory_id = chaos_api.memory_manager.remember(
        "李四喝牛奶",
        base_weight=0.2,
    )
    assert chaos_api.remember_triple("李四", "喝牛奶", "喝")
    with chaos_api.database_manager.get_connection() as connection:
        connection.execute(
            "UPDATE memories SET retrieval_count = ? WHERE id = ?",
            (9999, old_memory_id),
        )

    new_memory_id = chaos_api.memory_manager.remember(
        "李四乳糖不耐受，不喝牛奶",
        base_weight=1.0,
    )
    assert chaos_api.remember_triple("李四", "喝牛奶", "不喝")

    results = chaos_api.recall("牛奶", limit=10)
    recalled_ids = [result.memory_id for result in results]

    assert recalled_ids.index(new_memory_id) < recalled_ids.index(old_memory_id)
    assert results[recalled_ids.index(old_memory_id)].score == pytest.approx(0.3)

    with chaos_api.database_manager.get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, content, base_weight, retrieval_count, status, valid_to
            FROM memories
            WHERE id IN (?, ?)
            ORDER BY id
            """,
            (old_memory_id, new_memory_id),
        ).fetchall()
        edges = connection.execute(
            """
            SELECT edge.predicate, edge.valid_to, object.name AS object_name
            FROM edges AS edge
            JOIN entities AS subject
              ON subject.id = edge.subject_id
             AND subject.tenant_id = edge.tenant_id
            JOIN entities AS object
              ON object.id = edge.object_id
             AND object.tenant_id = edge.tenant_id
            WHERE edge.tenant_id = ? AND subject.name = ?
            ORDER BY edge.valid_from, edge.id
            """,
            ("default", "李四"),
        ).fetchall()

    assert len(rows) == 2
    old_row = next(row for row in rows if row["id"] == old_memory_id)
    new_row = next(row for row in rows if row["id"] == new_memory_id)
    assert old_row["retrieval_count"] == 9999
    assert old_row["base_weight"] == pytest.approx(0.2)
    assert old_row["status"] == "active"
    assert new_row["retrieval_count"] == 0
    assert new_row["base_weight"] == pytest.approx(1.0)
    assert len(edges) == 2
    assert edges[0]["object_name"] == "喝"
    assert edges[0]["valid_to"] is not None
    assert edges[1]["object_name"] == "不喝"
    assert edges[1]["valid_to"] is None


def test_rapid_fact_conflicts_leave_exactly_one_current_edge(
    chaos_api: RecallWeaverAPI,
) -> None:
    """Rapid residence changes close both historical edges atomically."""
    assert chaos_api.remember_triple("张三", "住在", "北京")
    assert chaos_api.remember_triple("张三", "住在", "上海")
    assert chaos_api.remember_triple("张三", "住在", "广州")

    with chaos_api.database_manager.get_connection() as connection:
        rows = connection.execute(
            """
            SELECT edge.predicate, edge.valid_from, edge.valid_to,
                   subject.name AS subject_name, object.name AS object_name
            FROM edges AS edge
            JOIN entities AS subject
              ON subject.id = edge.subject_id
             AND subject.tenant_id = edge.tenant_id
            JOIN entities AS object
              ON object.id = edge.object_id
             AND object.tenant_id = edge.tenant_id
            WHERE edge.tenant_id = ? AND subject.name = ?
            ORDER BY edge.valid_from, edge.id
            """,
            ("default", "张三"),
        ).fetchall()

    assert len(rows) == 3
    assert {row["subject_name"] for row in rows} == {"张三"}
    assert {row["predicate"] for row in rows} == {"住在"}
    edges_by_city = {row["object_name"]: row for row in rows}
    assert set(edges_by_city) == {"北京", "上海", "广州"}
    assert edges_by_city["北京"]["valid_to"] is not None
    assert edges_by_city["上海"]["valid_to"] is not None
    assert edges_by_city["广州"]["valid_to"] is None
    assert sum(row["valid_to"] is None for row in rows) == 1
    assert all(row["valid_from"] for row in rows)


def test_sql_injection_and_oversized_memory_are_stored_safely(
    chaos_api: RecallWeaverAPI,
) -> None:
    """Quoted SQL payloads stay data and a 500 KB memory remains intact."""
    malicious_text = "'; DROP TABLE edges; --"
    oversized_text = "无意义文本" * 50_000
    malicious_memory_id = chaos_api.add_memory(malicious_text)
    oversized_memory_id = chaos_api.add_memory(oversized_text)

    with chaos_api.database_manager.get_connection() as connection:
        stored_rows = connection.execute(
            """
            SELECT id, content, length(content) AS content_length, status
            FROM memories
            WHERE id IN (?, ?)
            ORDER BY id
            """,
            (malicious_memory_id, oversized_memory_id),
        ).fetchall()
        edge_table = connection.execute(
            """
            SELECT name, type
            FROM sqlite_master
            WHERE type = ? AND name = ?
            """,
            ("table", "edges"),
        ).fetchone()
        edge_count = connection.execute(
            "SELECT count(*) AS row_count FROM edges"
        ).fetchone()["row_count"]

    assert len(stored_rows) == 2
    malicious_row = next(
        row for row in stored_rows if row["id"] == malicious_memory_id
    )
    oversized_row = next(
        row for row in stored_rows if row["id"] == oversized_memory_id
    )
    assert malicious_row["content"] == malicious_text
    assert malicious_row["status"] == "active"
    assert oversized_row["content_length"] == len(oversized_text)
    assert oversized_row["content"] == oversized_text
    assert oversized_row["status"] == "active"
    assert edge_table["name"] == "edges"
    assert edge_table["type"] == "table"
    assert edge_count == 0


def test_empty_database_recall_and_history_are_clean(
    chaos_api: RecallWeaverAPI,
) -> None:
    """An initialized empty database returns empty collections without SQL leaks."""
    assert chaos_api.recall("张三", limit=3) == []
    assert chaos_api.get_history("张三", "住在") == []

    with chaos_api.database_manager.get_connection() as connection:
        counts = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM edges) AS edge_count,
                (SELECT count(*) FROM entities) AS entity_count,
                (SELECT count(*) FROM memories) AS memory_count
            """
        ).fetchone()

    assert counts["edge_count"] == 0
    assert counts["entity_count"] == 0
    assert counts["memory_count"] == 0
