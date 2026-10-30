"""事实冲突解决的边界场景集成测试。"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from recallweaver.db import db_manager
from recallweaver.errors import DatabaseError
from recallweaver.memory_manager import MemoryManager


@pytest.fixture
def memory_manager(monkeypatch: pytest.MonkeyPatch):
    """创建隔离的内存 SQLite 数据库，并载入项目实际 schema。"""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    schema_path = Path(__file__).resolve().parents[2] / "schema.sql"
    connection.executescript(schema_path.read_text(encoding="utf-8"))

    @contextmanager
    def get_memory_connection():
        """为内存连接提供与生产管理器相同的提交、回滚语义。"""
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


def _read_edges(
    manager: MemoryManager,
    *,
    tenant_id: str | None = None,
    subject: str | None = None,
):
    """读取边及两端名称，支持按租户和主语精确检查隔离行为。"""
    clauses = []
    parameters = []
    if tenant_id is not None:
        clauses.append("edge.tenant_id = ?")
        parameters.append(tenant_id)
    if subject is not None:
        clauses.append("subject.name = ?")
        parameters.append(subject)
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with manager.db.get_connection() as conn:
        return conn.execute(
            f"""
            SELECT edge.id, edge.tenant_id, edge.predicate,
                   edge.valid_from, edge.valid_to,
                   subject.name AS subject, object.name AS object
            FROM edges AS edge
            JOIN entities AS subject ON subject.id = edge.subject_id
            JOIN entities AS object ON object.id = edge.object_id
            {where_clause}
            ORDER BY edge.tenant_id, subject.name, edge.predicate, edge.valid_from
            """,
            parameters,
        ).fetchall()


def _parse_timestamp(value: str) -> datetime:
    """将数据库中的 UTC ISO 8601 时间转换为带时区的 datetime。"""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_conflict_closes_old_fact_and_starts_current_fact(
    memory_manager: MemoryManager,
) -> None:
    """值冲突保留旧事实时间区间，并将新值设为当前事实。"""
    manager = memory_manager
    manager.remember_with_conflict_resolution("张三", "住在", "北京")

    # 将旧事实的生效时间回拨，明确模拟时间旅行场景。
    old_valid_from = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
    with manager.db.get_connection() as conn:
        conn.execute(
            """
            UPDATE edges
            SET valid_from = ?
            WHERE tenant_id = ? AND predicate = ? AND valid_to IS NULL
              AND subject_id = (
                  SELECT id FROM entities
                  WHERE tenant_id = ? AND name = ?
              )
            """,
            (old_valid_from, "default", "住在", "default", "张三"),
        )

    before_new_fact = datetime.now(timezone.utc)
    manager.remember_with_conflict_resolution("张三", "住在", "上海")
    after_new_fact = datetime.now(timezone.utc)

    edges = _read_edges(manager, tenant_id="default", subject="张三")
    assert len(edges) == 2
    beijing = next(edge for edge in edges if edge["object"] == "北京")
    shanghai = next(edge for edge in edges if edge["object"] == "上海")

    assert beijing["valid_to"] is not None
    assert shanghai["valid_to"] is None
    assert _parse_timestamp(beijing["valid_from"]) < before_new_fact
    assert before_new_fact <= _parse_timestamp(shanghai["valid_from"]) <= after_new_fact
    assert beijing["valid_to"] == shanghai["valid_from"]


def test_different_predicates_do_not_conflict(
    memory_manager: MemoryManager,
) -> None:
    """同一主语的不同谓词代表不同事实，不得互相失效。"""
    manager = memory_manager
    manager.remember_with_conflict_resolution("张三", "住在", "北京")
    manager.remember_with_conflict_resolution("张三", "工作于", "字节跳动")

    edges = _read_edges(manager, tenant_id="default", subject="张三")
    assert len(edges) == 2
    assert {edge["predicate"] for edge in edges} == {"住在", "工作于"}
    assert all(edge["valid_to"] is None for edge in edges)


def test_tenants_cannot_expire_each_others_facts(
    memory_manager: MemoryManager,
) -> None:
    """租户 B 对同名主体的更新不得覆盖租户 A 的事实。"""
    manager = memory_manager
    manager.remember_with_conflict_resolution(
        "张三", "住在", "北京", tenant_id="tenant-a"
    )
    manager.remember_with_conflict_resolution(
        "张三", "住在", "上海", tenant_id="tenant-b"
    )

    tenant_a_edges = _read_edges(
        manager, tenant_id="tenant-a", subject="张三"
    )
    tenant_b_edges = _read_edges(
        manager, tenant_id="tenant-b", subject="张三"
    )
    assert len(tenant_a_edges) == 1
    assert len(tenant_b_edges) == 1
    assert tenant_a_edges[0]["object"] == "北京"
    assert tenant_b_edges[0]["object"] == "上海"
    assert tenant_a_edges[0]["valid_to"] is None
    assert tenant_b_edges[0]["valid_to"] is None


def test_exact_duplicate_is_idempotent(memory_manager: MemoryManager) -> None:
    """完全相同的事实重复写入不得产生重复边。"""
    manager = memory_manager
    manager.remember_with_conflict_resolution("李四", "养了", "旺财")
    manager.remember_with_conflict_resolution("李四", "养了", "旺财")

    edges = _read_edges(manager, tenant_id="default", subject="李四")
    matching_edges = [
        edge
        for edge in edges
        if edge["predicate"] == "养了" and edge["object"] == "旺财"
    ]
    assert len(matching_edges) == 1
    assert matching_edges[0]["valid_to"] is None


def test_failed_new_fact_insert_rolls_back_old_fact(
    memory_manager: MemoryManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模拟新边插入失败，验证旧边失效操作与新边一起回滚。"""
    manager = memory_manager
    manager.remember_with_conflict_resolution("张三", "住在", "北京")

    with manager.db.get_connection() as conn:
        shanghai_id = conn.execute(
            """
            SELECT id FROM entities
            WHERE tenant_id = ? AND name = ?
            """,
            ("default", "上海"),
        ).fetchone()
    assert shanghai_id is None

    original_get_connection = manager.db.get_connection

    class FailingInsertConnection:
        """只在目标新边 INSERT 时抛错，其余 SQL 交由真实 SQLite 执行。"""

        def __init__(self, connection: sqlite3.Connection) -> None:
            self._connection = connection

        def execute(self, sql: str, parameters=()):
            normalized_sql = " ".join(sql.split()).upper()
            if normalized_sql.startswith("INSERT INTO EDGES") and len(parameters) > 4:
                target_entity = self._connection.execute(
                    """
                    SELECT id FROM entities
                    WHERE tenant_id = ? AND name = ?
                    """,
                    (parameters[1], "上海"),
                ).fetchone()
                if target_entity is not None and parameters[4] == target_entity["id"]:
                    raise sqlite3.IntegrityError(
                        "simulated Shanghai edge failure"
                    )
            return self._connection.execute(sql, parameters)

    @contextmanager
    def failing_get_connection():
        """注入失败连接代理，同时保留原管理器的事务边界。"""
        with original_get_connection() as conn:
            yield FailingInsertConnection(conn)

    monkeypatch.setattr(manager.db, "get_connection", failing_get_connection)

    with pytest.raises(DatabaseError, match="写入或解决事实冲突失败"):
        manager.remember_with_conflict_resolution("张三", "住在", "上海")

    # 还原查询连接，避免读取操作经过故障注入代理。
    monkeypatch.setattr(manager.db, "get_connection", original_get_connection)
    edges = _read_edges(manager, tenant_id="default", subject="张三")
    assert len(edges) == 1
    assert edges[0]["object"] == "北京"
    assert edges[0]["valid_to"] is None
    with manager.db.get_connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM entities WHERE tenant_id = ? AND name = ?",
            ("default", "上海"),
        ).fetchone() is None
