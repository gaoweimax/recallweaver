"""Run a compact ablation of recency ranking and temporal fact resolution.

The script compares normal API recall with a recency-only baseline, then
contrasts unversioned text history with the graph's current fact timeline.
All experiments use temporary SQLite databases and leave no project data.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from recallweaver.api import RecallWeaverAPI

QUERY = "张三吃啥"
CORE_FACT = "朋友问张三吃啥？张三对花生过敏，不能吃花生。"
NOISE_COUNT_BEFORE = 100
NOISE_COUNT_AFTER = 50


def _write_noise(api: RecallWeaverAPI, count: int, offset: int) -> None:
    """Write unrelated chatter records with stable, unique contents.

    Args:
        api: API instance backed by an experiment-only database.
        count: Number of chatter memories to add.
        offset: Starting sequence number for unique chatter text.
    """
    for index in range(offset, offset + count):
        api.add_memory(
            f"群聊闲聊{index:03d}：今天天气不错，晚饭吃了米饭和青菜。"
        )


def _run_recall_ablation(api: RecallWeaverAPI) -> None:
    """Compare decay-aware recall with a recency-only ranking baseline.

    Args:
        api: API instance containing the 151-record recall corpus.
    """
    _write_noise(api, NOISE_COUNT_BEFORE, 0)
    core_memory_id = api.add_memory(CORE_FACT)
    _write_noise(api, NOISE_COUNT_AFTER, NOISE_COUNT_BEFORE)

    recall_results = api.recall(QUERY, limit=NOISE_COUNT_BEFORE + 1)
    assert recall_results, "完整流程没有召回任何结果"
    assert recall_results[0].memory_id == core_memory_id, (
        "完整流程中核心事实没有排在第 1 位"
    )
    assert "花生过敏" in recall_results[0].content

    with api.database_manager.get_connection() as conn:
        recency_rows = conn.execute(
            """
            SELECT id, content
            FROM memories
            WHERE tenant_id = ?
            ORDER BY rowid DESC
            """,
            ("default",),
        ).fetchall()
    recency_results: list[dict[str, Any]] = [
        dict(row) for row in recency_rows
    ]
    core_positions = [
        index
        for index, row in enumerate(recency_results, start=1)
        if row["id"] == core_memory_id
    ]
    assert len(recency_results) == (
        NOISE_COUNT_BEFORE + 1 + NOISE_COUNT_AFTER
    ), "消融基线数据条数不符合预期"
    assert core_positions == [NOISE_COUNT_AFTER + 1], (
        "仅按写入顺序排序时，核心事实未落在第 51 位"
    )
    assert all(
        "群聊闲聊" in row["content"]
        for row in recency_results[:NOISE_COUNT_AFTER]
    ), "核心事实之前的最近 50 条记录应全部为无关噪音"

    print("实验组 A（完整检索流程）")
    print(f"  查询：{QUERY}")
    print(f"  Top-1：{recall_results[0].content}")
    print("  结果：核心事实排在第 1 位")
    print("实验组 B（消融：忽略相关性与衰减，仅按最近写入排序）")
    print(f"  最近写入的噪音：{NOISE_COUNT_AFTER} 条")
    print(f"  核心事实排名：第 {core_positions[0]} 位")
    print("  结果：核心事实被最近写入的闲聊挤到第 51 位")


def _run_graph_ablation(db_path: Path) -> None:
    """Contrast unversioned text retrieval with graph fact history.

    Args:
        db_path: Temporary database path reserved for this experiment.
    """
    api = RecallWeaverAPI(str(db_path))
    api.add_memory("张三住在北京。")
    api.remember_triple("张三", "住在", "北京")
    api.add_memory("张三住在上海。")
    api.remember_triple("张三", "住在", "上海")

    with api.database_manager.get_connection() as conn:
        text_rows = conn.execute(
            """
            SELECT content
            FROM memories
            WHERE tenant_id = ? AND content LIKE ?
            ORDER BY rowid
            """,
            ("default", "%张三住在%"),
        ).fetchall()
    text_results = [str(row["content"]) for row in text_rows]
    assert len(text_results) == 2, "文本基线应同时返回两条居住地记忆"
    assert any("北京" in content for content in text_results)
    assert any("上海" in content for content in text_results)

    history = api.get_history("张三", "住在")
    assert len(history) == 2, "图谱历史应保留两个事实版本"
    current_facts = [fact for fact in history if fact["valid_to"] is None]
    assert len(current_facts) == 1, "图谱必须只保留一个当前有效事实"
    assert current_facts[0]["object"] == "上海"

    print("实验组 C（消融：仅查文本，不读取图谱有效状态）")
    print(f"  文本结果：{'；'.join(text_results)}")
    print("  结果：北京和上海同时出现，无法判断当前事实")
    print("  图谱时间线：")
    for fact in history:
        state = "当前有效" if fact["valid_to"] is None else "已失效"
        print(
            f"    {fact['object']}：{state} "
            f"(valid_from={fact['valid_from']}, valid_to={fact['valid_to']})"
        )


def main() -> None:
    """Execute all ablation cases using isolated temporary databases."""
    with tempfile.TemporaryDirectory(prefix="recallweaver-ablation-") as directory:
        root = Path(directory)
        recall_api = RecallWeaverAPI(str(root / "recall-ablation.sqlite3"))
        _run_recall_ablation(recall_api)
        _run_graph_ablation(root / "graph-ablation.sqlite3")


if __name__ == "__main__":
    main()