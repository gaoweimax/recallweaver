"""Network-free integration coverage for the DeepSeek memory demo."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
from openai import APITimeoutError
import pytest
from pytest_mock import MockerFixture
from rich.console import Console

from examples.deepseek_agent import DeepSeekAgent
from recallweaver.api import RecallWeaverAPI

ROUND_FOUR = (
    "我到底能不能吃花生？我以前是住哪来着，最近搬家累死了。"
)


@pytest.fixture
def demo_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[RecallWeaverAPI, DeepSeekAgent, StringIO]:
    """Create an isolated agent with a local database and captured output.

    Args:
        tmp_path: Per-test directory managed by pytest.
        monkeypatch: Fixture used to provide a non-secret test API key.

    Returns:
        A database API, configured demo agent, and Rich output buffer.
    """
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-key")
    output = StringIO()
    console = Console(file=output, force_terminal=False, width=120)
    api = RecallWeaverAPI(str(tmp_path / "deepseek-demo.sqlite3"))
    agent = DeepSeekAgent(api=api, console=console)
    return api, agent, output


def _mock_stream(text: str = "测试回复") -> list[Any]:
    """Build OpenAI-compatible streaming chunks without network access.

    Args:
        text: Content returned by the mocked model.

    Returns:
        A list with the shape consumed by ``DeepSeekAgent``.
    """
    return [
        SimpleNamespace(
            choices=[
                SimpleNamespace(delta=SimpleNamespace(content=text))
            ]
        )
    ]


def _mock_provider(
    agent: DeepSeekAgent,
    mocker: MockerFixture,
    *,
    text: str = "测试回复",
) -> Any:
    """Replace the provider call with an inspectable local mock.

    Args:
        agent: Agent whose SDK request must be intercepted.
        mocker: pytest-mock fixture.
        text: Mocked completion content.

    Returns:
        Mock for validating the request and its prompt.
    """
    return mocker.patch.object(
        agent.client.chat.completions,
        "create",
        return_value=_mock_stream(text),
    )


def _seed_time_and_allergy_facts(api: RecallWeaverAPI) -> None:
    """Create the historical facts needed to exercise turn-four prompting."""
    api.remember_triple("我", "住在", "北京")
    api.remember_triple("我", "住在", "杭州")
    api.remember_triple("我", "过敏", "花生")


def test_persona_and_fact_injection(
    demo_agent: tuple[RecallWeaverAPI, DeepSeekAgent, StringIO],
    mocker: MockerFixture,
) -> None:
    """Turn four sends persona, allergy, and both city versions to DeepSeek."""
    api, agent, _ = demo_agent
    _seed_time_and_allergy_facts(api)
    create_mock = _mock_provider(agent, mocker)

    agent.chat(ROUND_FOUR)

    kwargs = create_mock.call_args.kwargs
    assert kwargs["stream"] is True
    prompt = next(
        str(message["content"])
        for message in kwargs["messages"]
        if message["role"] == "system"
    )
    assert "毒舌" in prompt
    assert "花生" in prompt
    assert "北京(已失效)" in prompt
    assert "杭州" in prompt


def test_conflict_timestamp(
    demo_agent: tuple[RecallWeaverAPI, DeepSeekAgent, StringIO],
    mocker: MockerFixture,
) -> None:
    """Explicitly moving from Beijing to Hangzhou closes only the old edge."""
    api, agent, _ = demo_agent
    _mock_provider(agent, mocker)

    agent.chat("我以前住在北京，最近搬到了杭州。")

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
    assert set(validity) == {"北京", "杭州"}
    assert validity["北京"] is not None
    assert validity["杭州"] is None


def test_api_timeout_fallback(
    demo_agent: tuple[RecallWeaverAPI, DeepSeekAgent, StringIO],
    mocker: MockerFixture,
) -> None:
    """A provider timeout prints a red warning and returns a fallback reply."""
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

    answer = agent.chat(ROUND_FOUR)

    assert create_mock.call_args.kwargs["stream"] is True
    assert "DeepSeek 暂时连不上" in answer
    assert "DeepSeek 请求失败" in output.getvalue()
    assert "APITimeoutError" in output.getvalue()
    assert "Traceback" not in output.getvalue()
