"""记忆的持久化与实时权重查询功能。"""

# uuid 用于为每条记忆生成全球唯一标识，避免不同写入间发生主键冲突。
import uuid
# time 用于取得 Unix 时间戳，作为记忆创建和时间有效性的初始时刻。
import time
# sqlite3.Error 用于识别并转换数据库驱动产生的底层 SQL 异常。
import sqlite3
from datetime import datetime, timezone
from typing import Any

# 导入项目默认数据库管理器，所有读写操作都通过其连接上下文管理器完成。
from recallweaver.db import Database, db_manager
# 导入遗忘引擎，以便基于记忆权重和时间数据计算实时分数。
from recallweaver.decay_engine import DecayEngine
# 导入统一存储异常，让调用方无需直接依赖 SQLite 异常类型。
from recallweaver.errors import DatabaseError, StorageError, ValidationError


class MemoryManager:
    """负责将记忆写入数据库，并提供记忆读取与实时分数计算。"""

    def __init__(self, database: Database | None = None) -> None:
        """初始化管理器；未指定时复用项目默认数据库管理器。"""
        self.db = database or db_manager

    def remember(
        self,
        content: str,
        base_weight: float = 1.0,
        tenant_id: str = "default",
    ) -> str:
        """保存一条新记忆，并返回其唯一 ID。

        在写入记忆前先确保默认租户存在，因为 memories.tenant_id 是必填
        外键；随后为所有没有显式传入的记忆属性设置一致的初始值。
        """
        # 生成 UUID 并转成字符串，作为 memories 表的主键。
        memory_id = str(uuid.uuid4())
        # 使用秒级 Unix 时间戳初始化本次记忆相关的时间字段。
        now = int(time.time())
        try:
            # 使用数据库管理器提供的上下文管理器，正常结束时提交并关闭连接。
            with self.db.get_connection() as conn:
                # 必须先写入租户记录，以满足 memories.tenant_id 的外键约束。
                # INSERT OR IGNORE 使该操作在默认租户已存在时仍可安全重复执行。
                conn.execute(
                    """
                    INSERT OR IGNORE INTO tenants (id, name, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (tenant_id, "Default Tenant", now),
                )

                # 写入完整的记忆初始状态；其余可空字段由数据库默认值或 NULL 处理。
                conn.execute(
                    """
                    INSERT INTO memories (
                        id,
                        tenant_id,
                        content,
                        memory_type,
                        instruction_weight,
                        emotion_weight,
                        base_weight,
                        decay_lambda,
                        retrieval_count,
                        last_decay_at,
                        decayed_weight,
                        valid_from,
                        tx_time,
                        status,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        memory_id,
                        tenant_id,
                        content,
                        "fact",
                        1.0,
                        1.0,
                        base_weight,
                        0.01,
                        0,
                        now,
                        base_weight,
                        now,
                        now,
                        "active",
                        now,
                    ),
                )
        except sqlite3.Error as exc:
            # 将底层 SQLite 异常转换成项目统一的存储异常，并保留原始错误链。
            raise StorageError(f"保存记忆失败：{exc}") from exc

        # 只有数据库写入正常完成后才向调用方返回新记忆的标识。
        return memory_id

    def remember_with_conflict(
        self,
        content: str,
        conflict_keyword: str,
        base_weight: float = 5.0,
    ) -> str:
        """保存新记忆，并在同一事务内使匹配的旧记忆失效。

        双时间戳模型通过 ``valid_to`` 记录旧记忆在现实业务时间上的失效
        时刻，同时保留旧记录本身及其事务时间信息，从而不抹除历史事实。
        只有当前仍有效且状态为 active 的同租户记录会被设为 expired；
        新记录则从本次写入的时间点开始生效。

        参数:
            content: 新记忆的正文内容。
            conflict_keyword: 用于定位需要失效的旧记忆的字面子字符串。
            base_weight: 新记忆的初始基础权重，默认值为 5.0。

        返回:
            新建记忆的 UUID 字符串。

        异常:
            StorageError: 数据库连接、更新旧记忆或插入新记忆失败时抛出。
                所有写入使用同一连接和事务，因此失败时不会只保留部分变更。
        """
        # 在任何数据库操作之前生成新记录 ID 和统一时间点，保证新旧记录
        # 的 valid_to、valid_from、tx_time 与创建时间保持一致。
        memory_id = str(uuid.uuid4())
        now = int(time.time())
        tenant_id = "default"

        try:
            # 整个冲突处理过程复用同一连接；上下文管理器会在正常完成后提交，
            # 若中途抛出异常则关闭连接并由 SQLite 回滚尚未提交的事务。
            with self.db.get_connection() as conn:
                # 在外键约束生效的连接上先确保默认租户存在，避免后续记忆写入失败。
                # 使用参数绑定传值，并以 OR IGNORE 支持重复调用。
                conn.execute(
                    """
                    INSERT OR IGNORE INTO tenants (id, name, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (tenant_id, "Default Tenant", now),
                )

                # 步骤 A：只使默认租户中正文包含冲突关键词、当前仍有效且处于
                # active 状态的旧记忆失效。instr 按字面子字符串匹配，避免 LIKE
                # 中的百分号或下划线被误解释为通配符；关键词仍通过占位符绑定。
                conn.execute(
                    """
                    UPDATE memories
                    SET status = ?, valid_to = ?
                    WHERE tenant_id = ?
                      AND instr(content, ?) > 0
                      AND status = ?
                      AND valid_to IS NULL
                    """,
                    (
                        "expired",
                        now,
                        tenant_id,
                        conflict_keyword,
                        "active",
                    ),
                )

                # 步骤 B：新增取代旧事实的记忆。明确提供所有必要的初始字段，
                # valid_to 设为 NULL 表示新记录目前仍有效；未列出的可选字段
                # 由 schema 中的默认值或 NULL 处理。
                conn.execute(
                    """
                    INSERT INTO memories (
                        id,
                        tenant_id,
                        content,
                        memory_type,
                        instruction_weight,
                        emotion_weight,
                        base_weight,
                        decay_lambda,
                        retrieval_count,
                        last_decay_at,
                        decayed_weight,
                        valid_from,
                        valid_to,
                        tx_time,
                        status,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                    """,
                    (
                        memory_id,
                        tenant_id,
                        content,
                        "fact",
                        1.0,
                        1.0,
                        base_weight,
                        0.01,
                        0,
                        now,
                        base_weight,
                        now,
                        now,
                        "active",
                        now,
                    ),
                )
        except StorageError:
            # 数据库管理器已将 SQLite 错误转换为项目异常；保留该异常及原始原因。
            raise
        except sqlite3.Error as exc:
            # 防止未来数据库管理器实现变化导致底层 SQLite 异常泄漏到公共接口。
            raise StorageError(f"处理记忆冲突失败：{exc}") from exc

        # 只有租户准备、旧记忆失效和新记忆插入全部成功后才返回新 ID。
        return memory_id

    def remember_with_conflict_resolution(
        self,
        subject: str,
        predicate: str,
        object_: str,
        tenant_id: str = "default",
    ) -> bool:
        """以双时间戳写入事实，并原子化解决同一谓词的值冲突。

        ``valid_from`` 和 ``valid_to`` 使用 UTC ISO 8601 文本格式。完全重复
        的当前事实不会创建冗余边；值发生变化时，旧边失效和新边插入在同一
        数据库事务中完成，以确保失败时不会留下半完成状态。
        """
        if not all(
            isinstance(value, str) and value.strip()
            for value in (subject, predicate, object_, tenant_id)
        ):
            raise ValidationError("事实字段和租户标识均不能为空字符串")

        now_ts = datetime.now(timezone.utc).isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")
        created_at = int(time.time())

        try:
            with self.db.get_connection() as conn:
                try:
                    # 租户、实体和边在同一事务内创建，满足外键并保证原子性。
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO tenants (id, name, created_at)
                        VALUES (?, ?, ?)
                        """,
                        (tenant_id, tenant_id, created_at),
                    )

                    def get_or_create_entity(name: str) -> str:
                        """获取租户内实体 ID；缺失时创建规范名称相同的新实体。"""
                        row = conn.execute(
                            """
                            SELECT id
                            FROM entities
                            WHERE tenant_id = ? AND name = ?
                            ORDER BY id
                            LIMIT 1
                            """,
                            (tenant_id, name),
                        ).fetchone()
                        if row is not None:
                            return str(row["id"])

                        entity_id = str(uuid.uuid4())
                        conn.execute(
                            """
                            INSERT INTO entities (
                                id, tenant_id, name, canonical_name, created_at
                            )
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (entity_id, tenant_id, name, name, created_at),
                        )
                        return entity_id

                    subject_id = get_or_create_entity(subject)
                    object_id = get_or_create_entity(object_)

                    current_edges = conn.execute(
                        """
                        SELECT id, object_id
                        FROM edges
                        WHERE subject_id = ?
                          AND predicate = ?
                          AND valid_to IS NULL
                          AND tenant_id = ?
                        """,
                        (subject_id, predicate, tenant_id),
                    ).fetchall()

                    # 相同的当前事实为幂等成功，不更新也不插入冗余数据。
                    if current_edges and all(
                        edge["object_id"] == object_id for edge in current_edges
                    ):
                        return True

                    if current_edges:
                        # 关闭所有同主体、同谓词的当前版本，避免历史脏重复留下
                        # 多条有效边；随后仅插入一个新的当前事实。
                        conn.execute(
                            """
                            UPDATE edges
                            SET valid_to = ?
                            WHERE subject_id = ?
                              AND predicate = ?
                              AND valid_to IS NULL
                              AND tenant_id = ?
                            """,
                            (now_ts, subject_id, predicate, tenant_id),
                        )

                    conn.execute(
                        """
                        INSERT INTO edges (
                            id, tenant_id, subject_id, predicate, object_id,
                            valid_from, valid_to, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
                        """,
                        (
                            str(uuid.uuid4()),
                            tenant_id,
                            subject_id,
                            predicate,
                            object_id,
                            now_ts,
                            created_at,
                        ),
                    )
                except sqlite3.Error as exc:
                    # 抛出异常退出 with 块，数据库上下文管理器将回滚整笔事务。
                    raise DatabaseError(
                        f"写入或解决事实冲突失败：{exc}"
                    ) from exc
        except StorageError:
            raise

        return True

    def get_memory(self, memory_id: str) -> dict[str, Any]:
        """根据记忆 ID 读取记录；若记录不存在则抛出存储异常。"""
        # 通过统一连接管理器执行参数化查询，避免手动拼接 SQL 值。
        with self.db.get_connection() as conn:
            # 使用占位符传递 ID，查询该记忆的全部字段。
            row = conn.execute(
                "SELECT * FROM memories WHERE id = ?",
                (memory_id,),
            ).fetchone()

        # fetchone 在没有匹配记录时返回 None，明确报告不存在而不是返回空值。
        if row is None:
            raise StorageError(f"未找到 ID 为 {memory_id} 的记忆。")

        # 数据库连接设置了按列名访问的行工厂，因此可将行转换为普通字典返回。
        return dict(row)

    def get_realtime_score(self, memory_id: str) -> float:
        """读取记忆并使用遗忘引擎计算其当前实时分数。"""
        # 先读取记忆的基础权重、衰减系数、上次衰减时间和检索次数等计算数据。
        memory = self.get_memory(memory_id)

        # 将完整记录交给遗忘引擎；引擎根据其中相关字段返回实时分数。
        return DecayEngine.calculate_score(
            base_weight=memory["base_weight"],
            decay_lambda=memory["decay_lambda"],
            last_decay_at=memory["last_decay_at"],
            retrieval_count=memory["retrieval_count"],
        )