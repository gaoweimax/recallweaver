"""记忆的持久化与实时权重查询功能。"""

# uuid 用于为每条记忆生成全球唯一标识，避免不同写入间发生主键冲突。
import uuid
# time 用于取得 Unix 时间戳，作为记忆创建和时间有效性的初始时刻。
import time
# sqlite3.Error 用于识别并转换数据库驱动产生的底层 SQL 异常。
import sqlite3
# Dict 和 Any 用于描述以数据库列名为键、字段值为任意类型的记忆记录。
from typing import Dict, Any

# 导入项目默认数据库管理器，所有读写操作都通过其连接上下文管理器完成。
from recallweaver.db import db_manager
# 导入遗忘引擎，以便基于记忆权重和时间数据计算实时分数。
from recallweaver.decay_engine import DecayEngine
# 导入统一存储异常，让调用方无需直接依赖 SQLite 异常类型。
from recallweaver.errors import StorageError


class MemoryManager:
    """负责将记忆写入数据库，并提供记忆读取与实时分数计算。"""

    def remember(self, content: str, base_weight: float = 1.0) -> str:
        """保存一条新记忆，并返回其唯一 ID。

        在写入记忆前先确保默认租户存在，因为 memories.tenant_id 是必填
        外键；随后为所有没有显式传入的记忆属性设置一致的初始值。
        """
        # 生成 UUID 并转成字符串，作为 memories 表的主键。
        memory_id = str(uuid.uuid4())
        # 使用秒级 Unix 时间戳初始化本次记忆相关的时间字段。
        now = int(time.time())
        # 当前方法尚未接收调用方提供的租户，因此将新记忆保存至默认租户。
        tenant_id = "default"

        try:
            # 使用数据库管理器提供的上下文管理器，正常结束时提交并关闭连接。
            with db_manager.get_connection() as conn:
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

    def get_memory(self, memory_id: str) -> Dict[str, Any]:
        """根据记忆 ID 读取记录；若记录不存在则抛出存储异常。"""
        # 通过统一连接管理器执行参数化查询，避免手动拼接 SQL 值。
        with db_manager.get_connection() as conn:
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