"""图谱边写入与多跳关系查询。"""

import time
import uuid

from recallweaver.db import db_manager
from recallweaver.errors import StorageError


class GraphManager:
    """管理实体关系图的持久化和有界深度遍历。

    实体和关系边均按租户隔离；写入一条边时，实体、租户和边在同一
    SQLite 事务中创建，避免出现只有一端实体或不完整关系的状态。
    """

    def add_edge(
        self,
        subject: str,
        predicate: str,
        object_: str,
        tenant_id: str = "default",
    ) -> None:
        """确保关系两端实体存在，并写入一条有向关系边。

        实体按 ``(tenant_id, name)`` 查找；不存在时以名称同时作为
        ``name`` 和 ``canonical_name`` 创建。边的方向为 subject 到 object_。
        """
        now = int(time.time())

        try:
            with db_manager.get_connection() as conn:
                # 边和实体均引用租户外键；确保租户存在，并使重复写入保持幂等。
                conn.execute(
                    """
                    INSERT OR IGNORE INTO tenants (id, name, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (tenant_id, tenant_id, now),
                )

                def get_or_create_entity(name: str) -> str:
                    """在当前事务内查找租户实体，不存在时创建并返回其 ID。"""
                    row = conn.execute(
                        """
                        SELECT id
                        FROM entities
                        WHERE tenant_id = ? AND name = ?
                        ORDER BY created_at, id
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
                        (entity_id, tenant_id, name, name, now),
                    )
                    return entity_id

                subject_id = get_or_create_entity(subject)
                object_id = get_or_create_entity(object_)

                conn.execute(
                    """
                    INSERT INTO edges (
                        id, tenant_id, subject_id, predicate, object_id,
                        valid_from, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        tenant_id,
                        subject_id,
                        predicate,
                        object_id,
                        now,
                        now,
                    ),
                )
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(f"写入图谱关系失败：{exc}") from exc

    def get_neighbors(
        self,
        entity_name: str,
        depth: int = 2,
        tenant_id: str = "default",
    ) -> list:
        """从指定实体出发，沿有向关系查询最多 ``depth`` 跳的邻居。

        返回值按遍历深度排序，每项包含起点、终点实体名称及 ID、经过的
        关系路径和深度。只遍历当前有效边，并在每条路径内防止重复访问
        同一实体，避免环路造成无意义的递归扩张。
        """
        try:
            if not isinstance(depth, int) or isinstance(depth, bool) or depth < 1:
                raise ValueError("depth 必须是大于或等于 1 的整数")

            with db_manager.get_connection() as conn:
                rows = conn.execute(
                    """
                    WITH RECURSIVE graph_path(
                        start_id, end_id, relation, depth, visited_ids
                    ) AS (
                        SELECT
                            edge.subject_id,
                            edge.object_id,
                            edge.predicate,
                            1,
                            '/' || edge.subject_id || '/' || edge.object_id || '/'
                        FROM edges AS edge
                        JOIN entities AS start_entity
                          ON start_entity.id = edge.subject_id
                         AND start_entity.tenant_id = edge.tenant_id
                        WHERE start_entity.tenant_id = ?
                          AND start_entity.name = ?
                          AND edge.valid_to IS NULL

                        UNION ALL

                        SELECT
                            graph_path.start_id,
                            edge.object_id,
                            graph_path.relation || ' -> ' || edge.predicate,
                            graph_path.depth + 1,
                            graph_path.visited_ids || edge.object_id || '/'
                        FROM edges AS edge
                        JOIN graph_path
                          ON edge.subject_id = graph_path.end_id
                        WHERE edge.tenant_id = ?
                          AND edge.valid_to IS NULL
                          AND graph_path.depth < ?
                          AND instr(
                              graph_path.visited_ids,
                              '/' || edge.object_id || '/'
                          ) = 0
                    )
                    SELECT
                        graph_path.start_id,
                        start_entity.name AS start_name,
                        graph_path.end_id AS entity_id,
                        end_entity.name AS entity_name,
                        graph_path.relation,
                        graph_path.depth
                    FROM graph_path
                    JOIN entities AS start_entity
                      ON start_entity.id = graph_path.start_id
                     AND start_entity.tenant_id = ?
                    JOIN entities AS end_entity
                      ON end_entity.id = graph_path.end_id
                     AND end_entity.tenant_id = ?
                    ORDER BY graph_path.depth, end_entity.name, graph_path.relation
                    """,
                    (tenant_id, entity_name, tenant_id, depth, tenant_id, tenant_id),
                ).fetchall()

            return [dict(row) for row in rows]
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(f"查询图谱邻居失败：{exc}") from exc
