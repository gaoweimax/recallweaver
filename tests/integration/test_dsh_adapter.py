"""Integration tests for the DSH adapter and offline NAS startup checks."""

from pathlib import Path
from unittest.mock import patch

from plugins.dsh_adapter import DSHMemoryAdapter
from recallweaver.api import RecallWeaverAPI
from scripts import start_nas


def test_process_message_persists_memory_and_returns_system_prompt(
    tmp_path: Path,
) -> None:
    """The adapter persists a user's message and returns prompt-ready context."""
    db_path = str(tmp_path / "dsh-adapter.sqlite3")
    api = RecallWeaverAPI(db_path)
    adapter = DSHMemoryAdapter(api=api)

    # This adapter only prepares memory context; it must not make model requests.
    with patch("recallweaver.server.AsyncOpenAI") as openai_client:
        prompt = adapter.process_message("user_1", "大肥鱼我饿了")

    with api.database_manager.get_connection() as connection:
        stored = connection.execute(
            """
            SELECT content, tenant_id
            FROM memories
            WHERE tenant_id = ?
            """,
            ("user_1",),
        ).fetchall()

    openai_client.assert_not_called()
    assert len(stored) == 1
    assert stored[0]["content"] == "大肥鱼我饿了"
    assert "大肥鱼我饿了" in prompt
    assert "以下是你记得关于用户的事实" in prompt


def test_nas_startup_warns_in_red_and_does_not_start_a_real_server(
    monkeypatch,
) -> None:
    """Missing API key produces a red warning while Uvicorn remains mocked."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with (
        patch.object(start_nas, "console") as rich_console,
        patch.object(start_nas, "_local_ip_address", return_value="192.0.2.10"),
        patch.object(start_nas.subprocess, "run") as subprocess_run,
    ):
        subprocess_run.return_value.returncode = 0

        assert start_nas.main() == 0

    warning = rich_console.print.call_args.args[0]
    assert "[bold red]" in warning
    assert "未设置 DEEPSEEK_API_KEY" in warning
    subprocess_run.assert_called_once()
    command = subprocess_run.call_args.args[0]
    assert "recallweaver.server:app" in command
