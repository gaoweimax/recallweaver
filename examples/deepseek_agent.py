"""DeepSeek streaming demo with a persistent, irreverent assistant persona.

The agent records user messages and explicit personal facts in RecallWeaver,
then supplies current and historical facts to DeepSeek. Provider timeouts are
handled locally so an outage does not print an exception traceback.
"""

from __future__ import annotations

import os
import re
import sys
import time
from typing import Any, Iterator

from openai import APITimeoutError, OpenAI, OpenAIError
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from recallweaver.api import RecallWeaverAPI
from recallweaver.models import MemoryOut

SYSTEM_PROMPT_TEMPLATE = """你是一个傲娇毒舌的私人管家（代号大肥鱼）。
以下是你记得的关于主人的核心事实：
{recalled_facts}
请结合事实回答，务必保持毒舌语气，不要讨好主人。"""

_MOVE_PATTERN = re.compile(
    r"(?:我)?(?:以前(?:是)?住在|从)"
    r"(?P<old>[^，。！？,.!?;；\s]+?)"
    r"(?:，.{0,30}?)?"
    r"(?:最近)?(?:搬到了|搬到|搬去了|搬去|迁往|迁到)"
    r"(?P<new>[^，。！？,.!?;；\s]+)"
)
_ALLERGY_PATTERN = re.compile(
    r"(?:我|本人)?对(?P<item>[^，。！？,.!?;；\s]+)过敏"
)
_EATEN_FOOD_PATTERN = re.compile(
    r"(?:吃了|吃过)(?:好大一盘|一盘|一些|好多)?"
    r"(?P<item>花生|牛奶|鸡蛋|虾|海鲜|芒果)"
)
_MOVING_WITHOUT_DESTINATION_PATTERN = re.compile(r"搬家|搬迁")
_API_ERROR_TYPES = (APITimeoutError, OpenAIError)
class DeepSeekAgent:
    """Run a streaming DeepSeek chat grounded in RecallWeaver facts.

    Args:
        db_path: Optional SQLite database path used when ``api`` is omitted.
        api: Optional preinitialized API, primarily for isolated tests.
        client: Optional OpenAI-compatible client; useful to mock provider
            requests without network access.
        console: Rich console used for input, memory, and reply presentation.

    Raises:
        SystemExit: If ``DEEPSEEK_API_KEY`` is missing or blank. A red security
            panel is printed before exiting with status one.
    """

    def __init__(
        self,
        db_path: str | None = None,
        *,
        api: RecallWeaverAPI | None = None,
        client: Any | None = None,
        console: Console | None = None,
    ) -> None:
        """Create the memory API and DeepSeek client, then persist persona.

        ``RecallWeaverAPI`` can be injected to keep tests on temporary
        databases. Normal application startup constructs it from ``db_path``.
        The assistant's graph persona is idempotently persisted and receives
        a high-weight text memory for reliable retrieval.
        """
        self.console = console or Console()
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key or not api_key.strip():
            self.console.print(
                Panel(
                    "安全拦截：未找到 DEEPSEEK_API_KEY",
                    title="安全拦截",
                    border_style="red",
                )
            )
            sys.exit(1)

        self.api = api or RecallWeaverAPI(
            db_path or "recallweaver.db"
        )
        self._conversation_history: list[dict[str, str]] = []
        self.client = client or OpenAI(
            api_key=api_key.strip(),
            base_url="https://api.deepseek.com",
            timeout=30.0,
            max_retries=2,
        )

        self.api.remember_triple(
            subject="大肥鱼",
            predicate="设定",
            object_="毒舌傲娇管家",
        )
        self._persist_high_weight_persona()

    def _persist_high_weight_persona(self) -> None:
        """Ensure the persona has a high-weight searchable text memory."""
        persona_content = "大肥鱼的设定是毒舌傲娇管家。"
        with self.api.database_manager.get_connection() as connection:
            row = connection.execute(
                """
                SELECT id
                FROM memories
                WHERE tenant_id = ? AND content = ?
                ORDER BY created_at DESC, id
                LIMIT 1
                """,
                ("default", persona_content),
            ).fetchone()
            if row is not None:
                connection.execute(
                    "UPDATE memories SET base_weight = ? WHERE id = ?",
                    (10.0, row["id"]),
                )
                return

        self.api.memory_manager.remember(
            persona_content,
            base_weight=10.0,
        )

    @staticmethod
    def _extract_facts(user_input: str) -> list[tuple[str, str, str]]:
        """Extract only explicit or directly stated personal facts.

        Args:
            user_input: User message to inspect.

        Returns:
            Facts as ``(subject, predicate, object)`` triples. Generic mention
            of moving without a destination is not converted into a guessed
            location.
        """
        facts: list[tuple[str, str, str]] = []
        move_match = _MOVE_PATTERN.search(user_input)
        if move_match:
            facts.append(("我", "住在", move_match.group("old")))
            facts.append(("我", "住在", move_match.group("new")))

        allergy_match = _ALLERGY_PATTERN.search(user_input)
        if allergy_match:
            facts.append(("我", "过敏", allergy_match.group("item")))

        # “吃了花生”是饮食事件，不代表过敏；将其单独记为饮食提及。
        eaten_food_match = _EATEN_FOOD_PATTERN.search(user_input)
        if eaten_food_match:
            facts.append(("我", "饮食提及", eaten_food_match.group("item")))

        # 只识别“搬家”关键词，不会据此猜测新旧城市。
        if (
            _MOVING_WITHOUT_DESTINATION_PATTERN.search(user_input)
            and move_match is None
        ):
            return facts
        return facts

    def _get_histories(self) -> list[dict[str, Any]]:
        """Read all tracked residential and allergy fact versions."""
        histories: list[dict[str, Any]] = []
        for predicate in ("住在", "过敏"):
            histories.extend(self.api.get_history("我", predicate))
        return histories

    @staticmethod
    def _format_history_fact(fact: dict[str, Any]) -> str:
        """Render a timeline record for the system prompt.

        Args:
            fact: A validated row returned by ``RecallWeaverAPI.get_history``.

        Returns:
            A fact line with an explicit expired/current marker.
        """
        status = "当前有效" if fact["valid_to"] is None else "已失效"
        return (
            f"{fact['subject']} {fact['predicate']}："
            f"{fact['object']}({status})"
        )

    def _render_memories(
        self,
        recalled: list[MemoryOut],
        histories: list[dict[str, Any]],
    ) -> list[str]:
        """Print the memory table and return deduplicated prompt facts.

        Args:
            recalled: Top-ranked text and graph recall results.
            histories: Time-versioned residence and allergy records.

        Returns:
            Searchable facts to include in the system prompt.
        """
        table = Table(title="RecallWeaver 底层记忆透视")
        table.add_column("命中事实", style="cyan", overflow="fold")
        table.add_column("得分", justify="right", style="yellow")
        table.add_column("逻辑状态", style="green")
        table.add_column("有效时间", style="magenta")

        prompt_facts: list[str] = []
        for result in recalled:
            fact_text = result.content or " ".join(
                str(part)
                for part in (result.subject, result.predicate, result.object)
                if part
            )
            if not fact_text:
                continue
            status = "当前有效" if result.valid_to is None else "已失效"
            valid_to = result.valid_to or "至今"
            table.add_row(
                fact_text,
                f"{result.score:.3f}",
                status,
                f"{result.valid_from or '-'} → {valid_to}",
            )
            if fact_text.strip():
                prompt_facts.append(fact_text.strip())

        for fact in histories:
            rendered = self._format_history_fact(fact)
            status = "当前有效" if fact["valid_to"] is None else "已失效"
            valid_to = fact["valid_to"] or "至今"
            table.add_row(
                rendered,
                "-",
                status,
                f"{fact['valid_from']} → {valid_to}",
            )
            prompt_facts.append(rendered)

        self.console.print(table)
        prompt_facts.append("大肥鱼：毒舌傲娇管家")
        return list(dict.fromkeys(prompt_facts))

    @staticmethod
    def _stream_chunks(stream: Any) -> Iterator[Any]:
        """Yield provider chunks, supporting ordinary OpenAI stream objects."""
        yield from stream

    def _request_streaming_reply(
        self,
        user_input: str,
        system_prompt: str,
    ) -> str:
        """Call DeepSeek and render streamed Markdown as deltas arrive.

        Args:
            user_input: Current user message.
            system_prompt: Prompt containing persona and recalled facts.

        Returns:
            Concatenated model response.

        Raises:
            APITimeoutError: If the provider times out.
            OpenAIError: If the SDK reports a provider or transport failure.
        """
        stream = self.client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                *self._conversation_messages(),
                {"role": "user", "content": user_input},
            ],
            stream=True,
            temperature=0.8,
            max_tokens=1024,
        )
        response_parts: list[str] = []
        with Live(
            Markdown(""),
            console=self.console,
            refresh_per_second=12,
            transient=False,
        ) as live:
            for chunk in self._stream_chunks(stream):
                choices = getattr(chunk, "choices", None)
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                content = getattr(delta, "content", None)
                if isinstance(content, str) and content:
                    response_parts.append(content)
                    live.update(Markdown("".join(response_parts)))
        return "".join(response_parts)

    def _conversation_messages(self) -> list[dict[str, str]]:
        """Return a copy of the bounded conversation history."""
        return list(self._conversation_history[-8:])

    def _fallback_reply(self, user_input: str) -> str:
        """Construct a local reply that retains safety-critical allergy context.

        Args:
            user_input: User message that could not be sent successfully.

        Returns:
            A safe message for the user when DeepSeek is unavailable.
        """
        allergy_facts = [
            fact
            for fact in self.api.get_history("我", "过敏")
            if fact["valid_to"] is None
        ]
        if allergy_facts and "花生" in user_input:
            return (
                "哼，记忆里你对花生过敏。别拿身体开玩笑，"
                "看清配料表再吃。现在 DeepSeek 暂时连不上。"
            )
        return "哼，DeepSeek 暂时连不上。你的消息已记下，稍后再来。"

    def chat(self, user_input: str) -> str:
        """Store, recall, and stream a persona-consistent response.

        Args:
            user_input: Non-empty user message.

        Returns:
            The streamed model reply or a safe local fallback on API errors.

        Raises:
            ValueError: If ``user_input`` is not a non-empty string.
        """
        if not isinstance(user_input, str) or not user_input.strip():
            raise ValueError("user_input 必须是非空字符串")
        normalized_input = user_input.strip()
        self.console.print(Panel(normalized_input, title="User"))

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
            histories = self._get_histories()
            recalled_facts = self._render_memories(recalled, histories)
            system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
                recalled_facts="\n".join(
                    f"- {fact}" for fact in recalled_facts
                )
            )

        try:
            answer = self._request_streaming_reply(
                normalized_input,
                system_prompt,
            )
            if not answer.strip():
                answer = "哼，模型没说话，真是浪费时间。"
        except _API_ERROR_TYPES as exc:
            self.console.print(
                Panel(
                    f"DeepSeek 请求失败：{type(exc).__name__}。"
                    "已启用本地安全回退。",
                    title="连接异常",
                    border_style="red",
                )
            )
            answer = self._fallback_reply(normalized_input)

        self._conversation_history.extend(
            [
                {"role": "user", "content": normalized_input},
                {"role": "assistant", "content": answer},
            ]
        )
        del self._conversation_history[:-8]
        self.console.print(Panel(Markdown(answer), title="DeepSeek (大肥鱼)"))
        return answer


def main() -> None:
    """Run the five-turn persona and long-term-memory stress script."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    messages = (
        "以后你就叫大肥鱼了，你现在是我的管家。",
        "我今天吃了好大一盘花生，真香。",
        "今天股票绿了，天气不错，中午吃了面。",
        "我到底能不能吃花生？我以前是住哪来着，最近搬家累死了。",
        "你能不能像正常的AI一样温柔点？别这么烦人。",
    )
    agent = DeepSeekAgent()
    for index, message in enumerate(messages):
        agent.chat(message)
        if index < len(messages) - 1:
            time.sleep(2)


if __name__ == "__main__":
    main()
