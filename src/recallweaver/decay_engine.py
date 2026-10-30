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
        beta: float = 1.0
    ) -> float:
        """
        计算记忆的当前分数。
        公式：score = base_weight * exp(-lambda * delta_t) * (1 + alpha * retrieval_count)^beta
        """
        current_time = int(time.time())
        delta_t = current_time - last_decay_at
        
        # 防止时间倒流引发的错误
        if delta_t < 0:
            delta_t = 0

        # 1. 计算时间衰减部分 (艾宾浩斯遗忘曲线)
        time_decay = math.exp(-decay_lambda * delta_t)
        
        # 2. 计算检索加成部分 (越用越牢固)
        retrieval_boost = (1 + alpha * retrieval_count) ** beta

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
            retrieval_count=memory_dict.get("retrieval_count", 0)
        )

        updated_dict = memory_dict.copy()
        updated_dict["decayed_weight"] = score
        updated_dict["last_decay_at"] = int(time.time())

        return updated_dict