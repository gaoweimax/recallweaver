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
