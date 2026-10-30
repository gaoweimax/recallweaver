"""遗忘引擎的纯单元测试，不依赖数据库或外部服务。"""

# time 用于生成稳定表达“当前时刻”和“一年前”的 Unix 时间戳输入。
import time

# pytest 用于标记和执行遗忘分数的单元断言。
import pytest

# 导入被测算法；这些用例仅验证计算行为，不访问数据库。
from recallweaver.decay_engine import DecayEngine


def test_score_for_memory_from_one_year_ago_decays_to_zero() -> None:
    """默认衰减参数下，一年前的记忆应低于冷库阈值并返回 0。"""
    # 使用固定秒数近似一年，避免依赖时区或日历日期边界。
    one_year_ago = int(time.time()) - (365 * 24 * 60 * 60)

    # 默认基础权重和衰减系数对应指数衰减；过期分数应低于引擎的过滤阈值。
    score = DecayEngine.calculate_score(
        base_weight=1.0,
        decay_lambda=0.01,
        last_decay_at=one_year_ago,
        retrieval_count=0,
    )

    # calculate_score 对低于 0.05 的结果按设计直接返回 0.0。
    assert score == 0.0
    assert score == pytest.approx(0.0)


def test_high_retrieval_count_boosts_current_memory_above_one() -> None:
    """当前时间且检索次数很高时，使用加成应使分数超过基础权重。"""
    # 取当前整秒作为最近一次衰减时间，使测试中时间衰减部分接近 1。
    now = int(time.time())

    # 大量重复检索会通过 (1 + alpha * retrieval_count) 提升记忆分数。
    score = DecayEngine.calculate_score(
        base_weight=1.0,
        decay_lambda=0.01,
        last_decay_at=now,
        retrieval_count=100,
    )

    # 分数必须严格高于 1.0，验证检索加成确实参与最终计算。
    assert score > 1.0