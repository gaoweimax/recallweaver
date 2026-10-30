"""数据库初始化的集成测试。"""

# sqlite3 用于通过真实 SQLite 连接检查初始化后数据库中的表清单。
import sqlite3

# 从包公开接口导入默认数据库管理器，验证外部调用方可复用的初始化路径。
from recallweaver.db import db_manager


def test_init_db_creates_core_tables(tmp_path, monkeypatch):
    """初始化数据库后，核心记忆表和实体表应当存在。"""
    # 使用 pytest 提供的临时目录，避免测试读写开发者实际使用的数据库文件。
    database_path = tmp_path / "integration-test.db"
    # 将默认管理器的路径临时指向本测试专属数据库，pytest 会在测试结束时恢复它。
    monkeypatch.setattr(db_manager, "db_path", str(database_path))

    # 调用正式数据库初始化入口，执行项目根目录 schema.sql 中的建表语句。
    db_manager.init_db()

    # 直接使用 sqlite3 打开已初始化的文件，以独立方式验证实际落盘的表结构。
    with sqlite3.connect(database_path) as connection:
        # 查询 SQLite 系统目录中的普通表名称，供后续断言核心表确实已创建。
        table_rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()

    # 将 sqlite3 返回的单列元组列表转换为名称集合，便于清晰地检查必需表名。
    table_names = {row[0] for row in table_rows}

    # 记忆表和实体表是基础数据模型的核心，初始化后两者都必须存在。
    assert "memories" in table_names
    assert "entities" in table_names
