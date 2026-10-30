from typing import List, Dict, Any
from recallweaver.db import db_manager
from recallweaver.decay_engine import DecayEngine
from recallweaver.errors import StorageError

class Retriever:
    """记忆检索引擎"""
    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        try:
            with db_manager.get_connection() as conn:
                rows = []
                # 策略 1：尝试 FTS5 全文检索（极速匹配英文和完整分词）
                try:
                    sql_fts = """
                        SELECT m.* FROM memories m
                        JOIN memories_fts f ON m.rowid = f.rowid
                        WHERE f.memories_fts MATCH ? AND m.status = 'active'
                        LIMIT 50
                    """
                    cursor = conn.execute(sql_fts, (f"{query}*",))
                    rows = cursor.fetchall()
                except Exception:
                    pass # 如果 FTS 匹配不到，静默降级

                # 策略 2：FTS 没搜到（比如中文），直接使用 LIKE 模糊查询兜底
                if not rows:
                    sql_like = """
                        SELECT * FROM memories 
                        WHERE content LIKE ? AND status = 'active'
                        LIMIT 50
                    """
                    cursor = conn.execute(sql_like, (f"%{query}%",))
                    rows = cursor.fetchall()

                results = []
                for row in rows:
                    item = dict(row)
                    # 实时重算衰减分数
                    item["realtime_score"] = DecayEngine.calculate_score(
                        base_weight=item["base_weight"],
                        decay_lambda=item["decay_lambda"],
                        last_decay_at=item["last_decay_at"],
                        retrieval_count=item["retrieval_count"]
                    )
                    results.append(item)

                # 根据实时分数降序排序
                results.sort(key=lambda x: x["realtime_score"], reverse=True)
                return results[:limit]
                
        except Exception as e:
            raise StorageError(f"检索失败: {str(e)}")