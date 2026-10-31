"""Network-free integration tests for the FastAPI service."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pytest
from pytest_mock import MockerFixture

from recallweaver.api import RecallWeaverAPI
from recallweaver.server import ServerSettings, create_app


@pytest.fixture
def api(tmp_path: Path) -> RecallWeaverAPI:
    """Provide an isolated SQLite-backed memory API."""
    return RecallWeaverAPI(str(tmp_path / "server-test.sqlite3"))


def _mock_completion(reply: str = "测试回复") -> Any:
    """Build the subset of a completion response consumed by the service."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=reply))
        ]
    )


def _create_test_client(
    api: RecallWeaverAPI,
    mocker: MockerFixture,
) -> tuple[TestClient, AsyncMock]:
    """Patch the DeepSeek SDK and return a TestClient plus request mock."""
    create_mock = AsyncMock(return_value=_mock_completion())
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create_mock)
        ),
        close=AsyncMock(),
    )
    mocker.patch(
        "recallweaver.server.AsyncOpenAI",
        return_value=fake_client,
    )
    application = create_app(
        api=api,
        service_settings=ServerSettings(
            deepseek_api_key="test-key",
            db_path="unused-test-path.db",
        ),
    )
    return TestClient(application), create_mock


def test_chat_endpoint(
    api: RecallWeaverAPI,
    mocker: MockerFixture,
) -> None:
    """Chat returns the declared response and invokes only the mocked model."""
    client, create_mock = _create_test_client(api, mocker)

    with client:
        response = client.post(
            "/api/v1/chat",
            json={
                "user_id": "test-user",
                "message": "我对花生过敏",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "测试回复"
    assert body["recalled_facts"]
    assert isinstance(body["latency_ms"], float)
    assert "花生" in body["recalled_facts"][0]
    assert response.headers["X-Trace-ID"]
    create_mock.assert_awaited_once()
    assert create_mock.call_args.kwargs["stream"] is False
    system_prompt = create_mock.call_args.kwargs["messages"][0]["content"]
    assert "花生" in system_prompt


def test_invalid_input(
    api: RecallWeaverAPI,
    mocker: MockerFixture,
) -> None:
    """Blank chat messages are rejected by Pydantic with HTTP 422."""
    client, create_mock = _create_test_client(api, mocker)

    with client:
        response = client.post(
            "/api/v1/chat",
            json={"user_id": "test-user", "message": "   "},
        )

    assert response.status_code == 422
    create_mock.assert_not_awaited()

