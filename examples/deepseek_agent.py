"""DeepSeek chat demo grounded in RecallWeaver's time-versioned memories.

The demo extracts a small set of residence and allergy facts with explicit
rules, displays retrieved memory context, and streams a DeepSeek response.
All provider calls are bounded by a timeout and gracefully fall back on
network errors.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterator

from openai import APITimeoutError, OpenAI, OpenAIError
from rich.console import Console
from rich.panel import Panel
from rich.status import Status
from rich.table import Table

from recallweaver.api import RecallWeaverAPI
from recallweaver.models import MemoryOut

MOVE_PATTERN = re.compile(
    r"从(?P<old>[^，。！？,.!?;；\s]+?)"
    r"(?:搬到|搬去|搬到了|迁到|迁往)"
    r"(?P<new>[^，。！？,.!?;；\s]+)"
)
ALLERGY_PATTERN = re.compile(
    r"(?:我|本人)?对(?P<item>[^，。！？,.!?;；\s]+)过敏"
)
SYSTEM_PROMPT_TEMPLATE = """你是一个拥有长期记忆的私人助手。以下是你记得关于用户的事实：
{recalled_memories}
请结合上述记忆回答用户。若无相关记忆，请直接回答。"""
CHAT_MODEL = "deepseek-chat"


class DeepSeekAgent:
    """Run a memory-aware DeepSeek chat against an injected RecallWeaver API.

    Args:
        api: Initialized RecallWeaver API backed by the desired database.
        console: Optional Rich console for status, tables, and error panels.

    Raises:
        SystemExit: If ``DEEPSEEK_API_KEY`` is absent or blank. A red Rich
            panel is displayed before exiting.
    """

    def __init__(
        self,
        api: RecallWeaverAPI,
        console: Console | None = None,
    ) -> None:
        """Create a DeepSeek client using the key from the environment."""
        self.console = console or Console()
        self.api = api
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key or not api_key.strip():
            self.console.print(
                Panel(
                    "未设置环境变量 DEEPSEEK_API_KEY，无法启动 DeepSeek Demo。",
                    title="配置错误",
                    border_style="red",
                )
            )
            raise SystemExit(1)

        self.client = OpenAI(
            api_key=api_key.strip(),
            base_url="https://api.deepseek.com",
            timeout=30.0,
            max_retries=2,
        )

    @staticmethod
    def _extract_facts(user_input: str) -> list[tuple[str, str, str]]:
        """Extract supported residence and allergy facts from a user message.

        Args:
            user_input: Validated plain-text utterance.

        Returns:
            Ordered facts as ``(subject, predicate, object)`` triples. When a
            move explicitly names the prior city, that prior fact is emitted
            before the destination to preserve the temporal transition.
        """
        facts: list[tuple[str, str, str]] = []
        move_match = MOVE_PATTERN.search(user_input)
        if move_match:
            facts.append(("我", "住在", move_match.group("old")))
            facts.append(("我", "住在", move_match.group("new")))

        allergy_match = ALLERGY_PATTERN.search(user_input)
        if allergy_match:
            facts.append(("我", "过敏", allergy_match.group("item")))
        return facts

    def _get_fact_history(self) -> list[dict[str, Any]]:
        """Load relevant time-versioned residence and allergy histories.

        Returns:
            Histories for the user's residence and allergy predicates.
        """
        histories: list[dict[str, Any]] = []
        for predicate in ("住在", "过敏"):
            histories.extend(self.api.get_history("我", predicate))
        return histories

    @staticmethod
    def _format_history_fact(fact: dict[str, Any]) -> str:
        """Format one temporal fact with an explicit current/expired label.

        Args:
            fact: History record returned by RecallWeaver.

        Returns:
            A prompt-ready fact line, including an expired label when needed.
        """
        state = "当前有效" if fact["valid_to"] is None else "已失效"
        return (
            f"{fact['subject']} {fact['predicate']} "
            f"{fact['object']}({state})"
        )

    def _print_recall_table(
        self,
        recalled: list[MemoryOut],
        history: list[dict[str, Any]],
    ) -> None:
        """Display retrieved memories and fact validity using a Rich table.

        Args:
            recalled: Text and graph recall results.
            history: Residence and allergy temporal facts.
        """
        table = Table(title="RecallWeaver 时空记忆")
        table.add_column("命中事实", style="cyan", overflow="fold")
        table.add_column("得分", justify="right", style="yellow")
        table.add_column("逻辑状态", style="green")
        table.add_column("有效时间区间", style="magenta")

        for result in recalled:
            content = result.content or " ".join(
                str(part)
                for part in (result.subject, result.predicate, result.object)
                if part
            )
            state = "当前有效" if result.valid_to is None else "已失效"
            valid_to = result.valid_to or "至今"
            table.add_row(
                content or "(无文本内容)",
                f"{result.score:.3f}",
                state,
                f"{result.valid_from or '-'} → {valid_to}",
            )

        for fact in history:
            state = "当前有效" if fact["valid_to"] is None else "已失效"
            valid_to = fact["valid_to"] or "至今"
            table.add_row(
                f"{fact['subject']} {fact['predicate']} {fact['object']}",
                "-",
                state,
                f"{fact['valid_from']} → {valid_to}",
            )

        self.console.print(table)

    @staticmethod
    def _stream_text(chunks: Iterator[Any]) -> str:
        """Extract and concatenate text deltas from a chat completion stream.

        Args:
            chunks: Stream of OpenAI-compatible completion chunks.

        Returns:
            The concatenated assistant response.
        """
        parts: list[str] = []
        for chunk in chunks:
            choices = getattr(chunk, "choices", None)
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            content = getattr(delta, "content", None)
            if isinstance(content, str) and content:
                parts.append(content)
        return "".join(parts)

    def _fallback_response(self, history: list[dict[str, Any]]) -> str:
        """Create a local response when the DeepSeek request is unavailable.

        Args:
            history: Retrieved temporal personal facts.

        Returns:
            A short response that avoids claiming an unavailable model answer.
        """
        current_allergies = [
            str(fact["object"])
            for fact in history
            if fact["predicate"] == "过敏" and fact["valid_to"] is None
        ]
        if current_allergies:
            allergens = "、".join(current_allergies)
            return (
                f"我记得你对{allergens}过敏。DeepSeek 暂时不可用，"
                "请稍后再试；选择食物时请核对配料表。"
            )
        return "DeepSeek 暂时不可用，对话已保存，请稍后再试。"

    def chat(self, user_input: str) -> str:
        """Store, recall, and stream a context-aware answer for one message.

        Args:
            user_input: User utterance for this chat turn.

        Returns:
            The streamed assistant response, or a local fallback on provider
            timeout/network errors.

        Raises:
            ValueError: If user input is empty or not a string.
        """
        if not isinstance(user_input, str) or not user_input.strip():
            raise ValueError("user_input 必须是非空字符串")
        normalized_input = user_input.strip()

        with self.console.status(
            "⚡ 正在深度检索时空图谱与衰减池...",
            spinner="dots",
        ):
            self.api.add_memory(normalized_input)
            for subject, predicate, object_ in self._extract_facts(
                normalized_input
            ):
                self.api.remember_triple(subject, predicate, object_)

            recalled = self.api.recall(normalized_input, limit=3)
            history = self._get_fact_history()
            self._print_recall_table(recalled, history)

            recalled_memories = [
                self._format_history_fact(fact)
                for fact in history
            ]
            recalled_memories.extend(
                result.content
                for result in recalled
                if result.content and result.content != normalized_input
            )
            system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
                recalled_memories="\n".join(
                    f"- {memory}" for memory in dict.fromkeys(recalled_memories)
                )
            )

        self.console.print(Panel(system_prompt, title="System Prompt"))
        self.console.print(Panel(normalized_input, title="User"))

        try:
            stream = self.client.chat.completions.create(
                model=CHAT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": normalized_input},
                ],
                stream=True,
                temperature=0.7,
                max_tokens=1024,
            )
            answer = self._stream_text(iter(stream))
            if not answer:
                answer = "模型没有返回文本内容。"
        except (APITimeoutError, OpenAIError) as exc:
            self.console.print(
                Panel(
                    f"DeepSeek 请求失败：{type(exc).__name__}。已切换到本地回退回复。",
                    title="服务暂不可用",
                    border_style="red",
                )
            )
            answer = self._fallback_response(history)

        self.console.print(Panel(answer, title="DeepSeek"))
        return answer


def main() -> None:
    """Run a three-turn moving, noise, and history-recall demo."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    with tempfile.TemporaryDirectory(
        prefix="recallweaver-deepseek-agent-"
    ) as temporary_directory:
        database_path = Path(temporary_directory) / "deepseek-demo.sqlite3"
        api = RecallWeaverAPI(str(database_path))
        agent = DeepSeekAgent(api)
        for message in (
            "我以前住在北京，最近搬到了杭州，而且我对花生过敏。",
            "今天股票绿了，路上还买了杯咖啡。",
            "我以前住在哪里？",
        ):
            agent.chat(message)


if __name__ == "__main__":
    main()
