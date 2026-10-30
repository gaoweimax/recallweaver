"""记忆持久化、读取和双时间戳冲突处理的集成测试。"""

# sqlite3 用于直接检查数据库中的实际事务结果和时间有效性字段。
import sqlite3
# UUID 用于验证 remember 返回值遵守标准 UUID 格式。
from uuid import UUID

# pytest 用于夹具注入以及验证不存在记录时抛出的项目异常。
import pytest

# 导入被测记忆管理器和其对外报告的存储错误类型。
from recallweaver.errors import StorageError
from recallweaver.memory_manager import MemoryManager


def test_remember_reads_memory_and_calculates_realtime_score(test_database) -> None:
    """记忆写入后可按 ID 读取，且实时分数可正常计算。"""
    # 使用实际管理器实现，覆盖保存、查询和衰减分数计算的集成路径。
    manager = MemoryManager()

    # 写入一条内容唯一的记忆，并验证返回值可解析为合法 UUID。
    memory_id = manager.remember("自动化测试：记录一条普通记忆", base_weight=2.0)
    parsed_id = UUID(memory_id)
    assert str(parsed_id) == memory_id

    # 通过公开读取方法确认写入内容及传入的基础权重已经持久化。
    memory = manager.get_memory(memory_id)
    assert memory["id"] == memory_id
    assert memory["content"] == "自动化测试：记录一条普通记忆"
    assert memory["base_weight"] == pytest.approx(2.0)
    assert memory["status"] == "active"

    # 新记忆刚创建，实时分数应为正值且等于其初始基础权重附近的值。
    realtime_score = manager.get_realtime_score(memory_id)
    assert realtime_score > 0.0
    assert realtime_score == pytest.approx(2.0, rel=0.02)


def test_get_memory_for_unknown_id_raises_storage_error(test_database) -> None:
    """读取不存在的记忆必须以 StorageError 明确失败，不能伪装成空记录。"""
    # 创建管理器并为负向用例提供格式合法但数据库中不存在的 ID。
    manager = MemoryManager()
    unknown_memory_id = "00000000-0000-4000-8000-000000000000"

    # 断言错误类型符合项目约定，同时确保异常消息能指出查询目标。
    with pytest.raises(StorageError, match="未找到"):
        manager.get_memory(unknown_memory_id)


def test_remember_with_conflict_expires_old_record_and_keeps_new_record_active(
    test_database,
) -> None:
    """冲突写入应保留旧记录历史，并使新记忆成为当前有效记录。"""
    # 先持久化旧事实，确保后续冲突更新有明确的既有记录可供断言。
    manager = MemoryManager()
    old_memory_id = manager.remember("我住在北京")

    # 写入新事实时使用旧事实中的字面关键词触发旧记录失效。
    new_memory_id = manager.remember_with_conflict(
        "我搬到上海了",
        "北京",
    )

    # 使用同一独立测试数据库直接查看旧记录和新记录的落盘字段。
    with test_database.get_connection() as connection:
        old_record = connection.execute(
            "SELECT status, valid_to FROM memories WHERE id = ?",
            (old_memory_id,),
        ).fetchone()
        new_record = connection.execute(
            "SELECT status, valid_from, valid_to FROM memories WHERE id = ?",
            (new_memory_id,),
        ).fetchone()

    # 旧记忆不被删除，而是标记为失效并记录失效时间，以保留历史状态。
    assert old_record is not None
    assert old_record["status"] == "expired"
    assert old_record["valid_to"] is not None

    # 新事实从当前时刻开始生效，并以 NULL 失效时间表示仍然有效。
    assert new_record is not None
    assert new_record["status"] == "active"
    assert new_record["valid_from"] is not None
    assert new_record["valid_to"] is None


def test_conflict_transaction_rolls_back_old_record_expiration_on_insert_failure(
    test_database,
) -> None:
    """新记录插入失败时，旧记录的失效更新也必须回滚。"""
    # 创建一条将被冲突更新的记录，并记录其当前状态。
    manager = MemoryManager()
    old_memory_id = manager.remember("旧偏好：喜欢柚子")

    # 建立仅用于本测试数据库的触发器，强制指定新内容插入失败。
    with test_database.get_connection() as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_test_memory
            BEFORE INSERT ON memories
            WHEN NEW.content = 'forced test insert failure'
            BEGIN
                SELECT RAISE(ABORT, 'forced test insert failure');
            END
            """
        )

    # 验证失败按项目存储异常类型向上传递，而不是静默接受部分成功。
    with pytest.raises(StorageError):
        manager.remember_with_conflict(
            "forced test insert failure",
            "喜欢柚子",
        )

    # 事务原子性要求：新记忆插入失败后，旧记忆仍保持 active 且未设置失效时间。
    old_record = manager.get_memory(old_memory_id)
    assert old_record["status"] == "active"
    assert old_record["valid_to"] is None

    # 再检查失败的新记录没有残留，确保回滚覆盖了整个冲突写入事务。
    with test_database.get_connection() as connection:
        failed_record = connection.execute(
            "SELECT id FROM memories WHERE content = ?",
            ("forced test insert failure",),
        ).fetchone()
    assert failed_record is None
