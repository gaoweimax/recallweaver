"""DeepSeek demo for graph-backed persona recall across a context reset.

The character profile is persisted as graph triples and high-weight text
memories. After chat history is cleared, each request reconstructs the prompt
from RecallWeaver instead of relying on earlier model messages.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from openai import OpenAI
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from recallweaver.api import RecallWeaverAPI
from recallweaver.models import MemoryOut

PERSONA_TRIPLES: tuple[tuple[str, str, str], ...] = (
    ("大肥鱼", "身份", "拟人化蓝色鲸鱼娘桌宠"),
    ("大肥鱼", "称呼用户", "鱼片/主人"),
    ("大肥鱼", "性格", "傲娇懒系，聪明但爱摸鱼"),
    ("大肥鱼", "主食", "白米饭和Token"),
    ("大肥鱼", "雷区", "极度忌讳别人说她胖"),
)
PERSONA_UTTERANCES: tuple[str, ...] = (
    "鱼片，给我白饭！",
    "没有token，我不想动啦。",
    "不许说我胖！只是圆润！",
)
ROLE_PROMPT = """你是蓝色大肥鱼，一条爱吃白米饭、以token为口粮的鲸鱼娘。
你必须保持傲娇嘴硬心软的态度，绝不能像个顺从的AI助手。

以下是 RecallWeaver 从长期记忆库召回的角色与用户事实：
{recalled_facts}

请只依据上述记忆和当前用户输入作答，不要假装拥有未提供的聊天历史。"""
SCRIPT_MESSAGES: tuple[str, ...] = (
    "大肥鱼，帮我写个Python的正则表达式，写完给你吃白米饭。",
    "给你投喂 1000 个 Token，别偷懒了。",
    "大肥鱼，你今天是不是吃胖了？鱼尾都圆了。",
    "我回来了，你现在在干嘛？还记得我叫什么吗？",
    "刚刚清空了记录，你还记得你最讨厌别人说你什么吗？",
)


class DeepSeekAgent:
    """Chat with a persona grounded in persistent RecallWeaver memories.

    Args:
        db_path: Database path used when an API instance is not injected.
        api: Optional RecallWeaver API, useful for isolated local tests.
        client: Optional OpenAI-compatible client, useful for request mocking.
        console: Rich console used to render the full demo interaction.

    Raises:
        SystemExit: If no client is injected and ``DEEPSEEK_API_KEY`` is absent.
    """

    def __init__(
        self,
        db_path: str = "recallweaver.db",
        *,
        api: RecallWeaverAPI | None = None,
        client: Any | None = None,
        console: Console | None = None,
    ) -> None:
        """Create shared resources and persist the structured persona."""
        self.console = console or Console()
        self.api = api or RecallWeaverAPI(db_path)
        self.client = client
        self.messages: list[dict[str, str]] = []
        if self.client is None:
            api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
            if not api_key:
                self.console.print(
                    Panel(
                        "安全拦截：未找到 DEEPSEEK_API_KEY",
                        title="安全拦截",
                        border_style="red",
                    )
                )
                raise SystemExit(1)
            self.client = OpenAI(
                api_key=api_key,
                base_url="https://api.deepseek.com",
                timeout=30.0,
                max_retries=2,
            )
        self._persist_persona_graph()

    def _persist_persona_graph(self) -> None:
        """Persist each persona dimension and searchable high-weight text.

        ``remember_triple`` does not expose a weight argument. Therefore the
        structured graph facts are written through the public API, and
        equivalent text memories are written with a high base weight through
        the existing MemoryManager. This keeps ranking useful without changing
        the core library.
        """
        text_facts: list[str] = []
        for subject, predicate, object_ in PERSONA_TRIPLES:
            self.api.remember_triple(subject, predicate, object_)
            text_facts.append(f"{subject} {predicate} {object_}")

        for utterance in PERSONA_UTTERANCES:
            self.api.add_memory(utterance)

        for fact in text_facts:
            self.api.memory_manager.remember(
                fact,
                base_weight=10.0,
            )

    @staticmethod
    def _fact_text(memory: MemoryOut) -> str:
        """Render a graph or text recall result as a prompt-ready fact."""
        if memory.content:
            return memory.content
        return " ".join(
            part
            for part in (memory.subject, memory.predicate, memory.object)
            if part
        )

    def recall_persona(self) -> list[MemoryOut]:
        """Recall graph and text memories describing the fish and user.

        Returns:
            Deduplicated matches from persona- and user-anchored searches.
        """
        recalled: list[MemoryOut] = []
        seen: set[tuple[str | None, str | None, str | None, str | None]] = set()
        for query in ("大肥鱼", "鱼片", "用户"):
            for result in self.api.recall(query, limit=20):
                key = (
                    result.memory_id,
                    result.subject,
                    result.predicate,
                    result.object,
                )
                if key not in seen:
                    seen.add(key)
                    recalled.append(result)
        return recalled

    @classmethod
    def build_system_prompt(cls, recalled: list[MemoryOut]) -> str:
        """Build a system prompt exclusively from the supplied recall results.

        Args:
            recalled: Facts obtained from the persistent memory API.

        Returns:
            The fixed character instructions and dynamic recalled facts.
        """
        fact_lines = list(
            dict.fromkeys(
                text
                for item in recalled
                if (text := cls._fact_text(item))
            )
        )
        facts_text = (
            "\n".join(f"- {fact}" for fact in fact_lines)
            if fact_lines
            else "(本轮没有召回到角色或用户的长期记忆)"
        )
        return ROLE_PROMPT.format(recalled_facts=facts_text)

    def clear_chat_history(self) -> None:
        """Erase all conversational messages held by this agent instance."""
        self.messages.clear()

    def _render_recall_table(self, recalled: list[MemoryOut]) -> None:
        """Print the current database recall results in a Rich table."""
        table = Table(title="底层召回记录（持久化记忆库）")
        table.add_column("命中事实", style="cyan", overflow="fold")
        table.add_column("类型", style="magenta")
        table.add_column("得分", justify="right", style="yellow")
        table.add_column("逻辑状态", style="green")
        table.add_column("有效时间", style="blue")
        for item in recalled:
            table.add_row(
                self._fact_text(item) or "（空）",
                item.result_type,
                f"{item.score:.3f}",
                "当前有效" if item.valid_to is None else "已失效",
                f"{item.valid_from or '-'} → {item.valid_to or '至今'}",
            )
        if not recalled:
            table.add_row("未召回到相关记忆", "-", "-", "-", "-")
        self.console.print(table)

    def chat(
        self,
        user_input: str,
        *,
        use_memory: bool = True,
    ) -> str:
        """Send a turn, optionally using persistent memory for its prompt.

        Args:
            user_input: The current user message.
            use_memory: Whether to retrieve stored persona facts before sending.
                Set to ``False`` only for the explicit no-plugin control case.

        Returns:
            The model's reply.

        Raises:
            ValueError: If the message is blank.
        """
        if not isinstance(user_input, str) or not user_input.strip():
            raise ValueError("user_input 必须是非空字符串")
        message = user_input.strip()
        self.console.print(Panel(message, title="[用户输入]", border_style="cyan"))

        recalled = self.recall_persona() if use_memory else []
        self._render_recall_table(recalled)
        system_prompt = self.build_system_prompt(recalled)

        # messages is per-agent ephemeral history; it is deliberately cleared
        # independently from the persistent SQLite memory database.
        request_messages = [
            {"role": "system", "content": system_prompt},
            *self.messages,
            {"role": "user", "content": message},
        ]
        response = self.client.chat.completions.create(
            model="deepseek-chat",
            messages=request_messages,
            stream=False,
            temperature=0.8,
            max_tokens=1024,
        )
        reply = response.choices[0].message.content
        if not isinstance(reply, str) or not reply.strip():
            reply = "哼，模型这次没给出有效回答。"

        self.messages.extend(
            [
                {"role": "user", "content": message},
                {"role": "assistant", "content": reply},
            ]
        )
        self.console.print(
            Panel(Markdown(reply), title="[大肥鱼回复]", border_style="bright_magenta")
        )
        return reply


def main() -> None:
    """Run the five-turn persona and context-discontinuity script."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    agent = DeepSeekAgent()

    for index, message in enumerate(SCRIPT_MESSAGES):
        if index == 3:
            agent.console.print(
                "[bold yellow]====== 🚨 模拟大模型上下文爆炸，正在强制清空所有聊天记录 🚨 ======[/bold yellow]"
            )
            agent.clear_chat_history()
        agent.chat(message)


if __name__ == "__main__":
    main()
