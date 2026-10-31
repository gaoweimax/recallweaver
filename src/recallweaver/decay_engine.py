import math
import time
from typing import Any

class DecayEngine:
    """
    动态遗忘引擎（项目核心算法）。
    负责根据时间流逝和检索次数，计算记忆的动态权重分数。
    """

    @staticmethod
    def calculate_score(
        base_weight: float,
        decay_lambda: float,
        last_decay_at: int,
        retrieval_count: int = 0,
        alpha: float = 0.1,
        beta: float = 1.0,
        usefulness_weight: float = 1.0,
    ) -> float:
        """计算记忆的当前有效分数。

        Args:
            base_weight: 记忆写入时设置的基础权重。
            decay_lambda: 按秒计算的指数衰减速率。
            last_decay_at: 上次更新时间的 Unix 时间戳。
            retrieval_count: 累计检索次数。
            alpha: 每次检索的基础增幅系数。
            beta: 检索增幅的幂指数。
            usefulness_weight: 检索增幅的有用性权重；为零时检索次数不产生加成。

        Returns:
            应用于排序和截断的当前有效分数。检索增幅最多为 0.5 倍，
            即检索倍率最高为 1.5。

        Raises:
            ValueError: 当有用性权重不是有限的非负数时抛出。

        Notes:
            检索加成为 ``min(alpha * retrieval_count * usefulness_weight,
            0.5)``，再应用 ``beta``；最终倍率仍受 1.5 的硬上限约束。
            这避免反复检索无用内容时，其分数无限增长并挤占核心事实。
        """
        if (
            isinstance(usefulness_weight, bool)
            or not isinstance(usefulness_weight, (int, float))
            or not math.isfinite(usefulness_weight)
            or usefulness_weight < 0
        ):
            raise ValueError("usefulness_weight 必须是有限的非负数")

        current_time = int(time.time())
        delta_t = current_time - last_decay_at

        # 防止时间倒流引发的错误
        if delta_t < 0:
            delta_t = 0

        # 1. 计算时间衰减部分 (艾宾浩斯遗忘曲线)
        time_decay = math.exp(-decay_lambda * delta_t)

        # 2. 计算检索加成部分 (越用越牢固)
        weighted_boost = min(
            max(alpha * retrieval_count * usefulness_weight, 0.0),
            0.5,
        )
        retrieval_boost = min((1 + weighted_boost) ** beta, 1.5)

        # 3. 最终得分
        score = base_weight * time_decay * retrieval_boost

        # 4. 冷库阈值过滤（低于0.05直接视为遗忘）
        if score < 0.05:
            return 0.0

        return score

    @classmethod
    def update_decay(cls, memory_dict: dict[str, Any]) -> dict[str, Any]:
        """
        更新一条记忆的字典，返回最新的分数和时间戳，准备存回数据库。
        """
        score = cls.calculate_score(
            base_weight=memory_dict.get("base_weight", 1.0),
            decay_lambda=memory_dict.get("decay_lambda", 0.01),
            last_decay_at=memory_dict.get("last_decay_at", int(time.time())),
            retrieval_count=memory_dict.get("retrieval_count", 0),
            usefulness_weight=memory_dict.get(
                "usefulness_weight",
                memory_dict.get("base_weight", 1.0),
            ),
        )

        updated_dict = memory_dict.copy()
        updated_dict["decayed_weight"] = score
        updated_dict["last_decay_at"] = int(time.time())

        return updated_dict