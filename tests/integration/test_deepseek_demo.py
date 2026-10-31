"""Network-free tests for persona graph injection and context discontinuity."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from rich.console import Console
import pytest
from pytest_mock import MockerFixture

from examples.deepseek_agent import DeepSeekAgent
from recallweaver.api import RecallWeaverAPI


@pytest.fixture
def demo_agent(
    tmp_path: Path,
) -> tuple[RecallWeaverAPI, DeepSeekAgent, Mock, StringIO]:
    """Create an isolated graph database and local OpenAI-compatible mock.

    Args:
        tmp_path: Pytest's per-test temporary directory.

    Returns:
        The API, agent, provider create mock, and captured Rich output.
    """
    api = RecallWeaverAPI(str(tmp_path / "fish-persona.sqlite3"))
    create_mock = Mock(
        side_effect=[
            _completion("我在摸鱼，鱼片。"),
            _completion("不许说我胖！只是圆润！"),
            _completion("鱼片，我最讨厌别人说我胖！"),
        ]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create_mock)
        )
    )
    output = StringIO()
    console = Console(file=output, force_terminal=False, width=120)
    agent = DeepSeekAgent(api=api, client=client, console=console)
    return api, agent, create_mock, output


def _completion(content: str) -> Any:
    """Construct the response shape accessed by ``DeepSeekAgent.chat``."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=content))
        ]
    )


def _system_prompt(call: Any) -> str:
    """Extract the system prompt from a captured OpenAI request call."""
    return next(
        str(message["content"])
        for message in call.kwargs["messages"]
        if message["role"] == "system"
    )


def test_persona_facts_are_recalled_after_context_reset(
    demo_agent: tuple[RecallWeaverAPI, DeepSeekAgent, Mock, StringIO],
) -> None:
    """Round four and five prompts get their special facts from graph recall."""
    _, agent, create_mock, output = demo_agent
    agent.chat("大肥鱼，你今天是不是吃胖了？鱼尾都圆了。")
    agent.clear_chat_history()

    agent.chat("我回来了，你现在在干嘛？还记得我叫什么吗？")
    fourth_request = create_mock.call_args_list[1]
    fourth_prompt = _system_prompt(fourth_request)

    assert "鱼片" in fourth_prompt
    assert "胖" in fourth_prompt
    assert "Token" in fourth_prompt
    assert fourth_request.kwargs["messages"][-1] == {
        "role": "user",
        "content": "我回来了，你现在在干嘛？还记得我叫什么吗？",
    }
    assert [
        message["role"] for message in fourth_request.kwargs["messages"]
    ] == ["system", "user"]

    agent.chat("刚刚清空了记录，你还记得你最讨厌别人说你什么吗？")
    fifth_prompt = _system_prompt(create_mock.call_args_list[2])
    assert "鱼片" in fifth_prompt
    assert "胖" in fifth_prompt
    assert "Token" in fifth_prompt
    assert "底层召回记录" in output.getvalue()
    assert "模拟大模型上下文爆炸" not in output.getvalue()


def test_persona_graph_contains_all_required_dimensions(
    demo_agent: tuple[RecallWeaverAPI, DeepSeekAgent, Mock, StringIO],
) -> None:
    """Initialization writes every required setting as an individual triple."""
    api, _, _, _ = demo_agent

    with api.database_manager.get_connection() as connection:
        rows = connection.execute(
            """
            SELECT subject.name AS subject, edge.predicate, object.name AS object
            FROM edges AS edge
            JOIN entities AS subject
              ON subject.id = edge.subject_id
             AND subject.tenant_id = edge.tenant_id
            JOIN entities AS object
              ON object.id = edge.object_id
             AND object.tenant_id = edge.tenant_id
            WHERE edge.tenant_id = ?
              AND subject.name = ?
            """,
            ("default", "大肥鱼"),
        ).fetchall()

    graph_facts = {
        (str(row["subject"]), str(row["predicate"]), str(row["object"]))
        for row in rows
    }
    assert graph_facts == {
        ("大肥鱼", "身份", "拟人化蓝色鲸鱼娘桌宠"),
        ("大肥鱼", "称呼用户", "鱼片/主人"),
        ("大肥鱼", "性格", "傲娇懒系，聪明但爱摸鱼"),
        ("大肥鱼", "主食", "白米饭和Token"),
        ("大肥鱼", "雷区", "极度忌讳别人说她胖"),
    }

    with api.database_manager.get_connection() as connection:
        utterances = {
            str(row["content"])
            for row in connection.execute(
                """
                SELECT content
                FROM memories
                WHERE tenant_id = ? AND content IN (?, ?, ?)
                """,
                (
                    "default",
                    "鱼片，给我白饭！",
                    "没有token，我不想动啦。",
                    "不许说我胖！只是圆润！",
                ),
            ).fetchall()
        }
    assert utterances == {
        "鱼片，给我白饭！",
        "没有token，我不想动啦。",
        "不许说我胖！只是圆润！",
    }


def test_without_recall_prompt_does_not_contain_private_persona_facts(
    demo_agent: tuple[RecallWeaverAPI, DeepSeekAgent, Mock, StringIO],
    mocker: MockerFixture,
) -> None:
    """The no-recall control has no special facts despite persisted storage."""
    api, agent, create_mock, _ = demo_agent
    recall_spy = mocker.spy(api, "recall")

    agent.chat("你还记得我的专属设定吗？", use_memory=False)

    recall_spy.assert_not_called()
    prompt = _system_prompt(create_mock.call_args)
    assert "鱼片" not in prompt
    assert "胖" not in prompt
    assert "Token" not in prompt
    assert "本轮没有召回到角色或用户的长期记忆" in prompt

