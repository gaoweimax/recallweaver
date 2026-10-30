# 导入底层的核心引擎
from recallweaver.memory_manager import MemoryManager
from recallweaver.retrieval import Retriever
from recallweaver.errors import StorageError

# ==========================================
# 全局实例化（极其重要）
# ==========================================
# 为什么要在最外面实例化？因为每次调用都实例化会消耗内存，
# 全局只实例化一次，以后每次调用直接复用它们。
_manager = MemoryManager()
_retriever = Retriever()

# ==========================================
# 对外暴露的核心 API 函数
# ==========================================

def remember(content: str, base_weight: float = 1.0) -> str:
    """
    对外接口：存入一条新记忆。
    
    参数:
        content (str): 记忆的内容，比如 "我住在广州"。
        base_weight (float): 基础权重，默认是1.0。重要的事情可以设为10.0。
    返回:
        str: 生成的全局唯一 ID。
    """
    # 直接调用底层大内总管的 remember 方法
    return _manager.remember(content, base_weight)


def recall(query: str, limit: int = 5) -> list:
    """
    对外接口：根据关键词搜索记忆。
    
    参数:
        query (str): 你要搜的词，比如 "广州"。
        limit (int): 最多返回几条结果，默认5条。
    返回:
        list: 包含记忆详情的字典列表（带有实时衰减分数）。
    """
    # 直接调用底层搜索猎犬的 search 方法
    return _retriever.search(query, limit)


# 限制外部只能引用这两个函数，保持包的纯洁性
__all__ = ["remember", "recall"]