"""图谱事实冲突解决的 SQLite 内存数据库集成测试。"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

from recallweaver.db import db_manager
from recallweaver.errors import DatabaseError
from recallweaver.memory_manager import MemoryManager


@pytest.fixture
def memory_manager(monkeypatch: pytest.MonkeyPatch):
    """为每个测试建立独立的真正内存数据库，并使用真实项目 schema。"""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    schema_path = Path(__file__).resolve().parents[2] / "schema.sql"
    connection.executescript(schema_path.read_text(encoding="utf-8"))

    @contextmanager
    def get_memory_connection():
        """模拟生产连接管理器的提交与异常回滚语义。"""
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    monkeypatch.setattr(db_manager, "get_connection", get_memory_connection)
    try:
        yield MemoryManager()
    finally:
        connection.close()


def _read_edges(memory_manager: MemoryManager, subject: str):
    """按主语名称读取事实边及其对象名称，便于断言业务时间状态。"""
    with memory_manager.db.get_connection() as conn:
        return conn.execute(
            """
            SELECT edge.id, edge.predicate, edge.valid_from, edge.valid_to,
                   subject.name AS subject, object.name AS object
            FROM edges AS edge
            JOIN entities AS subject ON subject.id = edge.subject_id
            JOIN entities AS object ON object.id = edge.object_id
            WHERE edge.tenant_id = ? AND subject.name = ?
            ORDER BY edge.valid_from
            """,
            ("default", subject),
        ).fetchall()


def test_insert_new_fact(memory_manager: MemoryManager) -> None:
    """新事实应创建一条当前有效边，并使用 ISO 8601 时间戳。"""
    assert memory_manager.remember_with_conflict_resolution(
        "张三", "住在", "北京"
    )

    edges = _read_edges(memory_manager, "张三")
    assert len(edges) == 1
    assert edges[0]["object"] == "北京"
    assert edges[0]["valid_to"] is None
    parsed_valid_from = datetime.fromisoformat(
        edges[0]["valid_from"].replace("Z", "+00:00")
    )
    assert parsed_valid_from.tzinfo == timezone.utc


def test_fact_conflict_update(memory_manager: MemoryManager) -> None:
    """事实值改变时，应关闭旧边并在同一事务中新建当前边。"""
    memory_manager.remember_with_conflict_resolution("张三", "住在", "北京")
    before_update = datetime.now(timezone.utc)

    assert memory_manager.remember_with_conflict_resolution(
        "张三", "住在", "上海"
    )
    after_update = datetime.now(timezone.utc)

    edges = _read_edges(memory_manager, "张三")
    assert len(edges) == 2
    old_edge = next(edge for edge in edges if edge["object"] == "北京")
    current_edge = next(edge for edge in edges if edge["object"] == "上海")

    assert old_edge["valid_to"] is not None
    assert current_edge["valid_to"] is None
    expired_at = datetime.fromisoformat(old_edge["valid_to"].replace("Z", "+00:00"))
    assert before_update <= expired_at <= after_update
    assert old_edge["valid_to"] == current_edge["valid_from"]


def test_exact_duplicate_ignore(memory_manager: MemoryManager) -> None:
    """重复写入完全相同的当前事实时，不应产生第二条边。"""
    assert memory_manager.remember_with_conflict_resolution(
        "李四", "养了", "旺财"
    )
    assert memory_manager.remember_with_conflict_resolution(
        "李四", "养了", "旺财"
    )

    edges = _read_edges(memory_manager, "李四")
    assert len(edges) == 1
    assert edges[0]["object"] == "旺财"
    assert edges[0]["valid_to"] is None


def test_failed_new_edge_insert_rolls_back_expiration(
    memory_manager: MemoryManager,
) -> None:
    """插入新边失败时，旧边的失效更新必须回滚。"""
    memory_manager.remember_with_conflict_resolution("张三", "住在", "北京")
    with memory_manager.db.get_connection() as conn:
        conn.execute(
            """
            CREATE TRIGGER reject_shanghai_edge
            BEFORE INSERT ON edges
            WHEN NEW.object_id = (
                SELECT id FROM entities
                WHERE tenant_id = NEW.tenant_id AND name = '上海'
            )
            BEGIN
                SELECT RAISE(ABORT, 'forced edge insertion failure');
            END
            """
        )

    with pytest.raises(DatabaseError, match="写入或解决事实冲突失败"):
        memory_manager.remember_with_conflict_resolution("张三", "住在", "上海")

    edges = _read_edges(memory_manager, "张三")
    assert len(edges) == 1
    assert edges[0]["object"] == "北京"
    assert edges[0]["valid_to"] is None
