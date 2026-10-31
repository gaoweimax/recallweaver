import logging
import re
import sqlite3
from typing import Any

from recallweaver.db import Database, db_manager
from recallweaver.decay_engine import DecayEngine
from recallweaver.errors import StorageError

logger = logging.getLogger(__name__)


class Retriever:
    """记忆检索引擎"""

    SCORE_THRESHOLD = 0.3
    MAX_QUERY_TERMS = 12

    def __init__(
        self,
        database: Database | None = None,
        decay_engine: DecayEngine | None = None,
    ) -> None:
        """接收数据库和评分引擎依赖，缺省时维持旧调用方式。"""
        self.db = database or db_manager
        self.decay_engine = decay_engine or DecayEngine()

    def search(
        self,
        query: str,
        limit: int = 5,
        tenant_id: str = "default",
    ) -> list[dict[str, Any]]:
        try:
            # 将自然语言查询安全拆成 FTS5 词项，避免标点和完整句式导致
            # MATCH 语法错误或要求整句所有词同时出现在同一条记忆中。
            query_terms = list(dict.fromkeys(re.findall(r"\w+", query)))
            fts_query = " OR ".join(
                f'"{term}"*'
                for term in query_terms[: self.MAX_QUERY_TERMS]
            )
            with self.db.get_connection() as conn:
                rows = []
                # 策略 1：尝试 FTS5 全文检索（极速匹配英文和完整分词）
                if fts_query:
                    try:
                        sql_fts = """
                            SELECT m.* FROM memories m
                            JOIN memories_fts f ON m.rowid = f.rowid
                            WHERE memories_fts MATCH ?
                              AND m.status = 'active'
                              AND m.tenant_id = ?
                            ORDER BY bm25(memories_fts), m.base_weight DESC,
                                     m.created_at DESC, m.id
                            LIMIT 50
                        """
                        cursor = conn.execute(sql_fts, (fts_query, tenant_id))
                        rows = cursor.fetchall()
                    except sqlite3.Error:
                        logger.debug(
                            "FTS query failed; falling back to substring search",
                            exc_info=True,
                        )

                # 策略 2：FTS 没搜到（比如中文），直接使用 LIKE 模糊查询兜底
                if not rows:
                    sql_like = """
                        SELECT * FROM memories 
                        WHERE content LIKE ? AND status = 'active'
                          AND tenant_id = ?
                        ORDER BY base_weight DESC, created_at DESC, id
                        LIMIT 50
                    """
                    cursor = conn.execute(sql_like, (f"%{query}%", tenant_id))
                    rows = cursor.fetchall()

                results = []
                for row in rows:
                    item = dict(row)
                    # 实时重算衰减分数
                    item["realtime_score"] = self.decay_engine.calculate_score(
                        base_weight=item["base_weight"],
                        decay_lambda=item["decay_lambda"],
                        last_decay_at=item["last_decay_at"],
                        retrieval_count=item["retrieval_count"],
                        usefulness_weight=float(
                            item.get("usefulness_weight", item["base_weight"])
                        ),
                    )
                    results.append(item)

                # 根据实时分数降序排序
                results.sort(key=lambda x: x["realtime_score"], reverse=True)
                # 在截取数量前过滤低分候选，避免低质量记录进入上层 API。
                qualified_results = [
                    item
                    for item in results
                    if item["realtime_score"] >= self.SCORE_THRESHOLD
                ]
                return qualified_results[:limit]
                
        except Exception as e:
            raise StorageError(f"检索失败: {str(e)}")