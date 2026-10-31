"""Network-free integration tests for the DeepSeek memory demo."""

from __future__ import annotations

from io import StringIO
from types import SimpleNamespace
from typing import Any

import httpx
from openai import APITimeoutError
import pytest
from pytest_mock import MockerFixture
from rich.console import Console

from examples.deepseek_agent import DeepSeekAgent
from recallweaver.api import RecallWeaverAPI

FIRST_TURN = "我以前住在北京，最近搬到了杭州，而且我对花生过敏。"


@pytest.fixture
def demo_agent(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[RecallWeaverAPI, DeepSeekAgent, StringIO]:
    """Create an isolated agent with a dummy key and capturable Rich output.

    Args:
        tmp_path: Pytest's per-test temporary directory.
        monkeypatch: Fixture for temporary environment configuration.

    Returns:
        API, agent, and output stream for one isolated integration test.
    """
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-key")
    output = StringIO()
    console = Console(file=output, force_terminal=False, width=120)
    api = RecallWeaverAPI(str(tmp_path / "deepseek-demo.sqlite3"))
    agent = DeepSeekAgent(api=api, console=console)
    return api, agent, output


def _mock_stream(text: str = "测试回复") -> list[Any]:
    """Create OpenAI-compatible streaming chunks without network access.

    Args:
        text: Text to expose in the mocked delta.

    Returns:
        A one-item iterable compatible with the agent's stream parser.
    """
    return [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=text),
                )
            ]
        )
    ]


def _intercept_streaming_request(
    agent: DeepSeekAgent,
    mocker: MockerFixture,
    *,
    text: str = "测试回复",
) -> Any:
    """Replace the OpenAI SDK call with a local streaming mock.

    Args:
        agent: Agent whose provider client must not access the network.
        mocker: pytest-mock fixture.
        text: Mocked streamed answer.

    Returns:
        The mock object for inspecting prompt arguments.
    """
    return mocker.patch.object(
        agent.client.chat.completions,
        "create",
        return_value=_mock_stream(text),
    )


def test_first_turn_closes_previous_city_and_keeps_new_city_current(
    demo_agent: tuple[RecallWeaverAPI, DeepSeekAgent, StringIO],
    mocker: MockerFixture,
) -> None:
    """Moving from Beijing to Hangzhou creates a closed/open fact pair."""
    api, agent, _ = demo_agent
    _intercept_streaming_request(agent, mocker)

    agent.chat(FIRST_TURN)

    with api.database_manager.get_connection() as connection:
        rows = connection.execute(
            """
            SELECT object.name AS city, edge.valid_to
            FROM edges AS edge
            JOIN entities AS subject
              ON subject.id = edge.subject_id
             AND subject.tenant_id = edge.tenant_id
            JOIN entities AS object
              ON object.id = edge.object_id
             AND object.tenant_id = edge.tenant_id
            WHERE edge.tenant_id = ?
              AND subject.name = ?
              AND edge.predicate = ?
              AND object.name IN (?, ?)
            """,
            ("default", "我", "住在", "北京", "杭州"),
        ).fetchall()

    validity = {str(row["city"]): row["valid_to"] for row in rows}
    assert validity["北京"] is not None
    assert validity["杭州"] is None


def test_system_prompt_contains_allergy_current_city_and_expired_city(
    demo_agent: tuple[RecallWeaverAPI, DeepSeekAgent, StringIO],
    mocker: MockerFixture,
) -> None:
    """The actual system prompt includes current and historical graph facts."""
    _, agent, output = demo_agent
    create_mock = _intercept_streaming_request(agent, mocker)

    agent.chat(FIRST_TURN)

    request_kwargs = create_mock.call_args.kwargs
    assert request_kwargs["stream"] is True
    prompt_messages = request_kwargs["messages"]
    system_prompt = next(
        str(message["content"])
        for message in prompt_messages
        if message["role"] == "system"
    )
    assert "花生" in system_prompt
    assert "杭州" in system_prompt
    assert "北京(已失效)" in system_prompt
    assert "System Prompt" in output.getvalue()


def test_api_timeout_returns_rich_fallback_without_traceback(
    demo_agent: tuple[RecallWeaverAPI, DeepSeekAgent, StringIO],
    mocker: MockerFixture,
) -> None:
    """A provider timeout is shown as a Rich panel and returned gracefully."""
    _, agent, output = demo_agent
    timeout_error = APITimeoutError(
        request=httpx.Request(
            "POST",
            "https://api.deepseek.com/chat/completions",
        )
    )
    create_mock = mocker.patch.object(
        agent.client.chat.completions,
        "create",
        side_effect=timeout_error,
    )

    answer = agent.chat(FIRST_TURN)

    assert create_mock.call_args.kwargs["stream"] is True
    assert "DeepSeek 暂时不可用" in answer
    assert "服务暂不可用" in output.getvalue()
    assert "APITimeoutError" in output.getvalue()
    assert "Traceback" not in output.getvalue()
