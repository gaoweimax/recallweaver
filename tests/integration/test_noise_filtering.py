"""Verify that low-importance chatter is removed from public recall results."""

from recallweaver.api import RecallWeaverAPI


def test_recall_filters_low_weight_noise_and_keeps_core_fact(test_database) -> None:
    """Only the useful, high-weight memory should survive the score threshold."""
    api = RecallWeaverAPI(test_database.db_path)
    noise_id = api.memory_manager.remember(
        "推荐零食时，我今天股票绿了，随口聊聊行情。",
        base_weight=0.1,
    )
    fact_id = api.memory_manager.remember(
        "推荐零食时请避开花生，我对花生过敏。",
        base_weight=1.0,
    )

    # 即使噪音被异常频繁地检索，低基础权重也无法让其超过硬性阈值。
    with api.database_manager.get_connection() as connection:
        connection.execute(
            "UPDATE memories SET retrieval_count = ? WHERE id = ?",
            (100_000, noise_id),
        )

    results = api.recall("推荐零食", limit=3)
    recalled_ids = [result.memory_id for result in results]

    assert fact_id in recalled_ids
    assert noise_id not in recalled_ids
    assert recalled_ids == [fact_id]
