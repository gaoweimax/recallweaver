"""RecallWeaver 的 DSH（DeepSeek Harness）桌宠适配器。

给刚接触 Python 的 DSH 用户：
1. 先在运行 DSH 的同一个 Python 环境中安装 RecallWeaver：
   ``python -m pip install recallweaver``。如果使用尚未发布的源码版本，
   请在 RecallWeaver 项目根目录运行 ``python -m pip install -e .``。
2. 将本文件复制到 DSH 文档指定的插件目录。若 DSH 要求插件有特定入口
   名称，请在其插件入口中导入 ``DSHMemoryAdapter``，并保留下面的调用：
   ``adapter.process_message(user_id, message)``。
3. DSH 插件调用该方法后，会先将本轮消息写入对应用户的记忆空间，再检索
   相关事实；返回的字符串可直接作为本轮对话的 System Prompt。
4. 默认数据库路径取 RecallWeaver 的 ``RECALLWEAVER_DB_PATH`` 配置；
   未配置时使用当前工作目录下的 ``recallweaver.db``。如需指定其他路径，
   可在创建适配器时传入 ``db_path``。

本文件是一个轻量的 Python 桥接示例，并不依赖或假设 DSH 的特定插件 SDK。
"""

import os

from recallweaver.api import RecallWeaverAPI
from recallweaver.config import settings
from recallweaver.models import MemoryOut


class DSHMemoryAdapter:
    """将 RecallWeaver 的记忆读写能力桥接到 DSH 的 System Prompt。"""

    def __init__(
        self,
        db_path: str | None = None,
        api: RecallWeaverAPI | None = None,
    ) -> None:
        """创建适配器；通常无需参数，测试或自定义部署可注入数据库/API。"""
        configured_db_path = (
            db_path
            or os.environ.get("RECALLWEAVER_DB_PATH")
            or settings.db_path
        )
        self.api = api or RecallWeaverAPI(configured_db_path)

    @staticmethod
    def _fact_text(memory: MemoryOut) -> str:
        """把文本记忆或图谱事实转换成可放入提示词的一行文字。"""
        if memory.content:
            return memory.content

        # 图谱结果没有 content，使用关系的主语、关系和宾语组成自然语言片段。
        parts = (
            memory.subject or memory.start_name,
            memory.predicate or memory.relation,
            memory.object or memory.entity_name,
        )
        return " ".join(part for part in parts if part)

    def process_message(self, user_id: str, message: str) -> str:
        """写入并召回该用户的记忆，返回 DSH 可用的 System Prompt。

        DSH 侧只需提供用户标识和本轮消息；``user_id`` 同时作为 RecallWeaver
        的租户标识，确保不同桌宠用户之间的记忆互相隔离。
        """
        self.api.add_memory(message, tenant_id=user_id)
        recalled = self.api.recall(message, limit=5, tenant_id=user_id)

        # 保持事实顺序并去重，避免相同内容重复占用模型上下文。
        facts = list(
            dict.fromkeys(
                fact
                for memory in recalled
                if (fact := self._fact_text(memory))
            )
        )
        memory_context = (
            "\n".join(f"- {fact}" for fact in facts)
            if facts
            else "（暂无相关记忆）"
        )
        return (
            "你是一个拥有长期记忆的私人助手。\n"
            "以下是你记得关于用户的事实：\n"
            f"{memory_context}\n"
            "请结合上述记忆回答用户；若无相关记忆，请直接回答。"
        )

    def on_message(self, user_id: str, message: str) -> str:
        """提供 DSH 常见事件入口名称，返回与 process_message 相同的提示词。"""
        return self.process_message(user_id, message)
