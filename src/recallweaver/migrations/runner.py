"""数据库版本迁移执行器。

迁移文件按版本号递增排列；执行器读取当前数据库已应用的最大版本，
并且只在需要时运行尚未应用的初始化迁移。
"""

# sqlite3 提供 SQL 执行异常类型；数据库连接本身由项目 Database 管理器创建。
import sqlite3
# time 用于生成 schema_migrations.applied_at 所需的 Unix 时间戳整数。
import time
# Path 用于根据当前模块的位置查找同目录中的迁移 SQL 文件。
from pathlib import Path

# StorageError 是项目统一的存储错误类型，用于报告迁移文件和 SQL 执行问题。
from recallweaver.errors import StorageError
# Database 为迁移函数的数据库管理器参数提供明确的静态类型约束。
from recallweaver.db import Database


def run_migrations(db_manager: Database) -> None:
    """根据数据库记录执行尚未应用的初始化迁移。

    参数:
        db_manager: 提供 ``get_connection()`` 上下文管理器的数据库管理对象。

    目前项目包含 ``0001_init.sql`` 这一份初始迁移；后续版本可沿用相同的
    版本记录机制追加新的迁移文件，而无需重复执行已经应用的版本。
    """
    # 通过统一连接上下文管理器操作数据库，确保连接在成功或失败后都会关闭。
    with db_manager.get_connection() as conn:
        # 在首次查询版本前确保版本表存在；全新数据库尚未执行任何迁移，
        # 因而不能假设 schema_migrations 已由初始化 SQL 创建。
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at INTEGER NOT NULL
            )
            """
        )

        # 读取目前已成功记录的最高迁移版本；无记录时将 NULL 转为版本 0。
        version_row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()
        current_version = int(version_row[0])

        # 版本 1 或更高已应用时，无需再次运行初始化迁移，保持重复调用安全。
        if current_version >= 1:
            return

        # 迁移文件与本执行器放在同一目录，不依赖进程启动时的当前工作目录。
        migration_path = Path(__file__).with_name("0001_init.sql")

        try:
            # 使用 UTF-8 读取 SQL 文件，避免迁移脚本中的中文注释产生编码问题。
            migration_sql = migration_path.read_text(encoding="utf-8")
        except OSError as exc:
            # 文件缺失或不可读时提供明确的项目级异常，并保留原始操作系统异常。
            raise StorageError(
                f"无法读取数据库迁移文件 {migration_path}：{exc}"
            ) from exc

        try:
            # executescript 默认会提交现有事务，因此在 SQL 文本前显式开启事务，
            # 让建表语句和随后写入的版本记录能够作为同一个原子迁移提交。
            conn.executescript(f"BEGIN IMMEDIATE;\n{migration_sql}")

            # 仅当整个迁移脚本执行成功后，才记录版本 1 和当前 Unix 时间戳。
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (1, int(time.time())),
            )
        except sqlite3.Error as exc:
            # SQL 执行失败时转换为统一存储异常；外层连接上下文会回滚未提交事务。
            raise StorageError(f"执行数据库迁移 0001_init.sql 失败：{exc}") from exc