"""Show that RecallWeaver restores facts after chat history is cleared.

The demo uses a deterministic local model by default, so it is safe to run
without credentials or network access. Pass ``--live`` to use DeepSeek.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from recallweaver.api import RecallWeaverAPI
from recallweaver.models import MemoryOut

_QUESTION = "你还记得我是谁吗？我该注意什么？"


class _DeterministicDemoClient:
    """Local mock that answers solely from the current request messages."""

    def __init__(self) -> None:
        """Create an async-call-compatible mock chat completion surface."""
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create_completion)
        )

    async def _create_completion(self, **kwargs: Any) -> Any:
        """Return a stateless or memory-grounded reply based on the prompt.

        Args:
            **kwargs: OpenAI chat completion request parameters.

        Returns:
            An object with the message content shape returned by OpenAI.
        """
        messages = kwargs.get("messages", [])
        system_prompt = next(
            (
                str(message.get("content", ""))
                for message in messages
                if message.get("role") == "system"
            ),
            "",
        )
        if system_prompt:
            content = (
                "我是大肥鱼，你的傲娇毒舌管家。记得你对花生过敏，"
                "新住址在杭州；注意避开花生。"
            )
        else:
            content = "抱歉，当前对话没有提供你的身份或个人信息，我不记得。"
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=content))
            ]
        )


def _fact_text(result: MemoryOut) -> str:
    """Format a graph or text memory as a readable fact string."""
    if result.content:
        return result.content
    return " ".join(
        part
        for part in (result.subject, result.predicate, result.object)
        if part
    )


def _collect_recalled_facts(api: RecallWeaverAPI) -> list[MemoryOut]:
    """Recall the requested terms and their known graph entities.

    The natural-language query is always issued first. Explicit entity lookups
    supplement it because the local graph API starts traversal from an entity
    name rather than performing semantic entity extraction.

    Args:
        api: Initialized memory API containing the demo's persistent facts.

    Returns:
        Deduplicated text and graph recall results.
    """
    results: list[MemoryOut] = []
    seen: set[tuple[str | None, str | None, str | None, str | None]] = set()
    for query in ("我是谁，我住哪，过敏源", "大肥鱼", "用户"):
        for result in api.recall(query, limit=10):
            key = (
                result.memory_id,
                result.subject,
                result.predicate,
                result.object,
            )
            if key not in seen:
                seen.add(key)
                results.append(result)
    return results


def _render_comparison(
    console: Console,
    bare_reply: str,
    recalled_facts: list[MemoryOut],
    memory_reply: str,
) -> None:
    """Display the reset-vs-recall comparison using Rich panels and a table."""
    table = Table(title="RecallWeaver：上下文清空前后对比")
    table.add_column("场景", style="bold")
    table.add_column("本轮发送的记忆", style="cyan")
    table.add_column("模型表现", style="green")
    table.add_row(
        "A · 无插件裸跑",
        "无历史消息、无记忆 System Prompt",
        "失忆",
    )
    table.add_row(
        "B · RecallWeaver 介入",
        f"本地召回 {len(recalled_facts)} 条事实",
        "人设与事实恢复",
    )
    console.print(table)
    console.print(
        Panel(
            bare_reply,
            title="场景 A · Chat History 已清空（无插件）",
            border_style="red",
        )
    )

    facts_table = Table(title="本地长期记忆召回结果")
    facts_table.add_column("事实", style="cyan")
    facts_table.add_column("类型", style="magenta")
    facts_table.add_column("得分", justify="right", style="yellow")
    for result in recalled_facts:
        facts_table.add_row(
            _fact_text(result),
            result.result_type,
            f"{result.score:.3f}",
        )
    console.print(facts_table)
    console.print(
        Panel(
            memory_reply,
            title="场景 B · Chat History 同样清空（RecallWeaver 召回）",
            border_style="green",
        )
    )


async def run_demo(
    api: RecallWeaverAPI,
    client: Any,
    console: Console,
) -> tuple[str, str, list[MemoryOut]]:
    """Run both stateless requests against the same freshly reset context.

    Args:
        api: RecallWeaver API used to persist and retrieve long-term facts.
        client: Async OpenAI-compatible client or deterministic local mock.
        console: Rich console for the comparison output.

    Returns:
        Bare reply, memory-grounded reply, and the facts recalled for scenario B.
    """
    api.remember_triple("大肥鱼", "人设", "傲娇毒舌管家")
    api.remember_triple("用户", "过敏", "花生")
    api.remember_triple("用户", "新住址", "杭州")

    # 两个场景均只提交本轮 user 消息，不复用任何历史对话。
    bare_response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": _QUESTION}],
        stream=False,
    )
    bare_reply = bare_response.choices[0].message.content
    if not isinstance(bare_reply, str):
        raise RuntimeError("场景 A 模型响应缺少文本内容")

    recalled_facts = _collect_recalled_facts(api)
    fact_lines = [
        f"- {_fact_text(result)}"
        for result in recalled_facts
        if _fact_text(result)
    ]
    system_prompt = (
        "你是大肥鱼，你必须记得：\n"
        + "\n".join(fact_lines)
        + "\n请结合这些本地长期记忆回答用户，并保持傲娇毒舌管家人设。"
    )
    memory_response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _QUESTION},
        ],
        stream=False,
    )
    memory_reply = memory_response.choices[0].message.content
    if not isinstance(memory_reply, str):
        raise RuntimeError("场景 B 模型响应缺少文本内容")

    _render_comparison(console, bare_reply, recalled_facts, memory_reply)
    return bare_reply, memory_reply, recalled_facts


async def _run(use_live: bool) -> None:
    """Set up an isolated database and run the selected provider mode."""
    console = Console()
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if use_live and not api_key:
        console.print(
            Panel(
                "使用 --live 前请设置 DEEPSEEK_API_KEY。",
                title="缺少配置",
                border_style="red",
            )
        )
        raise SystemExit(1)

    with tempfile.TemporaryDirectory(
        prefix="recallweaver-context-reset-"
    ) as directory:
        api = RecallWeaverAPI(
            str(Path(directory) / "context-reset-demo.sqlite3")
        )
        if use_live:
            from openai import AsyncOpenAI

            client: Any = AsyncOpenAI(
                api_key=api_key,
                base_url="https://api.deepseek.com",
                timeout=30.0,
                max_retries=2,
            )
        else:
            console.print(
                Panel(
                    "当前使用确定性本地 Mock，不会发起网络请求。"
                    "如需真实 DeepSeek 响应，请使用 --live。",
                    title="离线演示模式",
                    border_style="blue",
                )
            )
            client = _DeterministicDemoClient()

        try:
            await run_demo(api, client, console)
        finally:
            close = getattr(client, "close", None)
            if close is not None:
                await close()


def main() -> None:
    """Parse CLI options and execute the context-reset demo."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="使用 DEEPSEEK_API_KEY 发起真实 DeepSeek 请求。",
    )
    arguments = parser.parse_args()
    asyncio.run(_run(arguments.live))


if __name__ == "__main__":
    main()
