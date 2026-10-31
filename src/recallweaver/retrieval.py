import logging
import re
import sqlite3
from typing import Any

from recallweaver.db import Database, db_manager
from recallweaver.decay_engine import DecayEngine
from recallweaver.errors import StorageError

logger = logging.getLogger(__name__)

_QUERY_TOKEN_PATTERN = re.compile(r"[\u3400-\u9fff]+|[^\W_]+", re.UNICODE)
_CJK_PATTERN = re.compile(r"^[\u3400-\u9fff]+$")
_PUNCTUATION_PATTERN = re.compile(r"[^\w\s]|_", re.UNICODE)


def _build_trigram_query(query: str, max_terms: int) -> str:
    """Normalize a natural-language query into safe trigram FTS terms.

    Chinese runs become overlapping three-character phrases because FTS5's
    trigram tokenizer does not produce searchable tokens for one- or
    two-character input. Latin words remain intact so English substrings use
    the same tokenizer. Punctuation is excluded by lexical tokenization.

    Args:
        query: Raw user-provided search query.
        max_terms: Maximum number of generated FTS phrases.

    Returns:
        A quoted, OR-connected FTS5 expression, or an empty string when the
        query has no searchable terms.
    """
    if max_terms <= 0:
        return ""
    terms: list[str] = []
    for token in _QUERY_TOKEN_PATTERN.findall(query):
        if _CJK_PATTERN.fullmatch(token):
            token_terms = [
                token[index : index + 3]
                for index in range(len(token) - 2)
            ]
        elif len(token) >= 3:
            token_terms = [token]
        else:
            token_terms = []
        for term in token_terms:
            if term not in terms:
                terms.append(term)
    if len(terms) > max_terms:
        selected_indexes = {
            round(index * (len(terms) - 1) / (max_terms - 1))
            for index in range(max_terms)
        }
        terms = [
            term for index, term in enumerate(terms) if index in selected_indexes
        ]
    return " OR ".join(
        f'"{term}"'
        for term in terms
    )


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
            fts_query = _build_trigram_query(query, self.MAX_QUERY_TERMS)
            like_query = _PUNCTUATION_PATTERN.sub("", query).strip()
            with self.db.get_connection() as conn:
                rows = []
                # 优先通过重叠中文三元组或英文词项匹配自然语言子串。
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

                # FTS 无有效三元组、表达式失败或未命中时退回 LIKE。
                if not rows and like_query:
                    sql_like = """
                        SELECT * FROM memories 
                        WHERE content LIKE ? AND status = 'active'
                          AND tenant_id = ?
                        ORDER BY base_weight DESC, created_at DESC, id
                        LIMIT 50
                    """
                    cursor = conn.execute(
                        sql_like,
                        (f"%{like_query}%", tenant_id),
                    )
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