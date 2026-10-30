import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root / "src"))

from recallweaver.decay_engine import DecayEngine

print("=== 开始测试遗忘引擎 ===")
# 造一个一小时前的时间戳（3600秒前）
one_hour_ago = int(time.time()) - 3600

# 场景 1：一小时前的普通闲聊（基础权重低，衰减快）
casual_memory = {
    "base_weight": 1.0,
    "decay_lambda": 0.0005,  # 调小一点，让一小时不至于直接灰飞烟灭
    "last_decay_at": one_hour_ago,
    "retrieval_count": 0
}

# 场景 2：一小时前的核心指令（比如：我对花生过敏，绝不能吃）
core_memory = {
    "base_weight": 10.0, 
    "decay_lambda": 0.0005,
    "last_decay_at": one_hour_ago,
    "retrieval_count": 0
}

# 场景 3：核心指令，且用户在这一小时内提了 10 次（越提越深刻）
hot_core_memory = {
    "base_weight": 10.0,
    "decay_lambda": 0.0005,
    "last_decay_at": one_hour_ago,
    "retrieval_count": 10 
}

print(f"【1】一小时前的普通闲聊得分: {DecayEngine.calculate_score(**casual_memory):.4f}")
print(f"【2】一小时前的核心指令得分: {DecayEngine.calculate_score(**core_memory):.4f}")
print(f"【3】一小时前提过10次的核心指令得分: {DecayEngine.calculate_score(**hot_core_memory):.4f}")