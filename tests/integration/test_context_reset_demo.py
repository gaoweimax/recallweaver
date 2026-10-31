"""Network-free tests for the long-term memory context-reset demonstration."""

from __future__ import annotations

import asyncio
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from rich.console import Console

from examples.context_reset_demo import run_demo
from recallweaver.api import RecallWeaverAPI


def _completion(content: str) -> Any:
    """Return a minimal completion object with the OpenAI SDK response shape."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=content))
        ]
    )


def test_context_reset_recalls_persistent_persona_and_facts(
    tmp_path: Path,
) -> None:
    """Both requests omit chat history; only the second includes local facts."""
    api = RecallWeaverAPI(str(tmp_path / "context-reset-test.sqlite3"))
    request_mock = AsyncMock(
        side_effect=[
            _completion("我不记得你的身份或个人信息。"),
            _completion("我是大肥鱼，记得你对花生过敏并住在杭州。"),
        ]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=request_mock)
        )
    )
    output = StringIO()
    console = Console(file=output, force_terminal=False, width=120)

    bare_reply, restored_reply, recalled = asyncio.run(
        run_demo(api, client, console)
    )

    assert "不记得" in bare_reply
    assert "大肥鱼" in restored_reply
    recalled_text = [_memory_text(item) for item in recalled]
    assert any("傲娇毒舌管家" in fact for fact in recalled_text)
    assert any("花生" in fact for fact in recalled_text)
    assert any("杭州" in fact for fact in recalled_text)

    calls = request_mock.await_args_list
    assert len(calls) == 2
    first_messages = calls[0].kwargs["messages"]
    second_messages = calls[1].kwargs["messages"]
    assert first_messages == [
        {
            "role": "user",
            "content": "你还记得我是谁吗？我该注意什么？",
        }
    ]
    assert [message["role"] for message in second_messages] == [
        "system",
        "user",
    ]
    system_prompt = second_messages[0]["content"]
    assert "傲娇毒舌管家" in system_prompt
    assert "花生" in system_prompt
    assert "杭州" in system_prompt
    assert "Chat History 已清空" in output.getvalue()
    assert "RecallWeaver 介入" in output.getvalue()


def _memory_text(memory: Any) -> str:
    """Format a recalled graph/text fact for concise test assertions."""
    if memory.content:
        return memory.content
    return " ".join(
        part
        for part in (memory.subject, memory.predicate, memory.object)
        if part
    )
