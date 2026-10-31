"""全文检索及实时分数结果字段的集成测试。"""

# 导入记忆写入器和被测检索器，使用真实 SQLite FTS5 / LIKE 检索流程。
from recallweaver.memory_manager import MemoryManager
from recallweaver.retrieval import Retriever


def test_search_returns_matching_memory_with_realtime_score(test_database) -> None:
    """检索文本应命中保存的记忆，并附带计算后的实时分数。"""
    # 在专属测试数据库中写入中文内容，检验当前检索实现对中文文本的召回。
    content = "我是一只大肥鱼"
    memory_id = MemoryManager().remember(content)

    # 搜索关键词片段；检索器可先尝试 FTS5，必要时使用 LIKE 中文兜底查询。
    results = Retriever().search("肥鱼")

    # 结果列表应包含目标记录，且包含供调度和业务排序使用的实时衰减分数。
    assert any(result["id"] == memory_id for result in results)
    matching_result = next(
        result for result in results if result["id"] == memory_id
    )
    assert matching_result["content"] == content
    assert "realtime_score" in matching_result
    assert matching_result["realtime_score"] > 0.0


def test_chinese_substring_search(test_database) -> None:
    """A natural Chinese query matches separated substrings in one memory."""
    content = "我今天去杭州西湖吃了小笼包"
    memory_id = MemoryManager(database=test_database).remember(content)

    retriever = Retriever(database=test_database)
    for query in ("杭州小笼包", "杭州，小笼包！"):
        results = retriever.search(query)
        matching_results = [
            result for result in results if result["id"] == memory_id
        ]
        assert len(matching_results) == 1
        assert matching_results[0]["content"] == content


def test_chinese_no_space_search(test_database) -> None:
    """A Chinese substring without spaces matches via trigram indexing."""
    content = "张三对花生过敏"
    memory_id = MemoryManager(database=test_database).remember(content)

    results = Retriever(database=test_database).search("花生过敏")

    assert any(result["id"] == memory_id for result in results)


def test_english_and_pinyin(test_database) -> None:
    """The trigram tokenizer retains substring search for English terms."""
    content = "我在用 Python 写 RecallWeaver"
    memory_id = MemoryManager(database=test_database).remember(content)
    retriever = Retriever(database=test_database)

    for query in ("Python", "Recall"):
        results = retriever.search(query)
        assert any(result["id"] == memory_id for result in results)


def test_legacy_fts_table_is_rebuilt_with_trigram(test_database) -> None:
    """Database initialization migrates an existing default-tokenized FTS table."""
    memory_manager = MemoryManager(database=test_database)
    content = "我今天去杭州西湖吃了小笼包"
    memory_id = memory_manager.remember(content)

    with test_database.get_connection() as connection:
        connection.execute("DROP TABLE memories_fts")
        connection.execute(
            """
            CREATE VIRTUAL TABLE memories_fts USING fts5(
                content,
                content='memories',
                content_rowid='rowid'
            )
            """
        )

    test_database.init_db(verbose=False)
    results = Retriever(database=test_database).search("杭州小笼包")

    assert any(result["id"] == memory_id for result in results)
    with test_database.get_connection() as connection:
        definition = connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'table' AND name = 'memories_fts'
            """
        ).fetchone()["sql"]
    assert "tokenize='trigram'" in definition.lower()
